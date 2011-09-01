import os
import sys
import time
import ssl
import socket
import select
import threading
import Queue
from kitsu.http.errors import *
from kitsu.http.headers import *
from kitsu.http.request import *
from kitsu.http.response import *
from kitsu.http.sockets import *
from kitsu.http.sockets import HTTPClient
import unittest

server_keyfile = os.path.join(os.path.dirname(__file__), 'certs', 'server.key')
server_certfile = os.path.join(os.path.dirname(__file__), 'certs', 'server.crt')
server_ca_certs = os.path.join(os.path.dirname(__file__), 'certs', 'ca.crt')

class Server(threading.Thread):
    def __init__(self, host='127.0.0.1', port=0):
        threading.Thread.__init__(self)
        self.sock = socket.socket()
        self.sock.bind((host, port))
        self.sock.listen(1)
        self.sock.settimeout(5)
        self.host, self.port = self.sock.getsockname()
        self.responses = Queue.Queue()
        self.deadsockets = []
        self.secure = False
    
    def enqueue(self, response, autoclose=False):
        self.responses.put((response, autoclose))
    
    def run(self):
        try:
            while True:
                item = self.responses.get()
                if item is None:
                    break
                response, autoclose = item
                sock, addr = self.sock.accept()
                sock.settimeout(5)
                if self.secure:
                    sock = ssl.wrap_socket(sock, keyfile=server_keyfile, certfile=server_certfile, server_side=True)
                try:
                    parser = RequestParser()
                    while True:
                        data = sock.recv(4096)
                        assert data, "not enough data in server thread, likely a bug"
                        request = parser.parse(data)
                        if request:
                            assert parser.done
                            assert len(request) == 1
                            request = request[0]
                            break
                    #print "%s %s -> %d %s%s" % (request.method, request.target, response.code, response.phrase, response.body and " (%d bytes)" % len(response.body) or "")
                    sock.sendall(response.toString())
                    if response.body:
                        sock.sendall(response.body)
                finally:
                    if autoclose:
                        sock.close()
                    else:
                        self.deadsockets.append(sock)
                    sock = None
        finally:
            self.sock.close()
            self.sock = None
    
    def stop(self):
        self.responses.put(None)

class ProxyServer(threading.Thread):
    def __init__(self, host='127.0.0.1', port=0):
        threading.Thread.__init__(self)
        self.sock = socket.socket()
        self.sock.bind((host, port))
        self.sock.listen(1)
        self.sock.settimeout(5)
        self.host, self.port = self.sock.getsockname()
        self.targets = Queue.Queue()
    
    def enqueue(self, host, port):
        self.targets.put((host, port))
    
    def run(self):
        try:
            while True:
                target = self.targets.get()
                if target is None:
                    break
                host, port = target
                sock, addr = self.sock.accept()
                sock.settimeout(5)
                try:
                    parser = RequestParser()
                    while True:
                        data = sock.recv(4096)
                        assert data, "not enough data in server thread, likely a bug"
                        request = parser.parse(data)
                        if request:
                            assert parser.done
                            assert len(request) == 1
                            request = request[0]
                            assert request.method == 'CONNECT'
                            data = parser.clear()
                            break
                    #print "%s %s -> %s:%s" % (request.method, request.target, host, port)
                    target = socket.socket()
                    target.settimeout(5)
                    target.connect((host, port))
                    try:
                        sock.sendall('HTTP/1.1 200 OK\r\n\r\n')
                        if data:
                            target.sendall(data)
                        while True:
                            r, w, e = select.select([sock, target], [], [], 5)
                            for (src,dst) in ((sock, target), (target, sock)):
                                if src in r:
                                    data = src.recv(4096)
                                    if not data:
                                        break
                                    dst.sendall(data)
                            else:
                                continue
                            break
                    finally:
                        target.close()
                        target = None
                finally:
                    sock.close()
                    sock = None
        finally:
            self.sock.close()
            self.sock = None
    
    def stop(self):
        self.targets.put(None)

NORMAL_BODY = "Hello world"
CHUNKED_BODY = ("""\
%(size)X
%(chunk)s
%(size)X; test=1
%(chunk)s
0

""" % dict(size=len(NORMAL_BODY), chunk=NORMAL_BODY)).replace("\n", "\r\n")
CHUNKED_HEADER = ("""\
%(size)X
%(chunk)s
%(size)X; test=1
%(chunk)s
0
%%s: %%s

""" % dict(size=len(NORMAL_BODY), chunk=NORMAL_BODY)).replace("\n", "\r\n")

def make_response(body, chunked=False, length=None, code=200, headers=()):
    headers = Headers(headers)
    if chunked:
        headers['Transfer-Encoding'] = 'chunked'
    else:
        headers['Content-Length'] = ['ignore me', str(length or len(body))]
    return Response(code=code, body=body, headers=headers)

class HTTPClientTests(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.server.start()
    
    def tearDown(self):
        self.server.stop()
        self.server.join()
        self.server = None
    
    def request(self, response, request=None, autoclose=False, timeout=5, sizelimit=None, bodylimit=None):
        sock = socket.socket()
        sock.settimeout(timeout * 2)
        self.server.enqueue(response, autoclose=autoclose)
        sock.connect((self.server.host, self.server.port))
        start = time.time()
        try:
            return HTTPClient(sock, sizelimit=sizelimit, bodylimit=bodylimit).makeRequest(request or Request())
        finally:
            self.assertTrue(time.time() - start < timeout, "request took too long")
    
    def test_normal(self):
        # Test normal body (no Content-Length)
        response = self.request(Response(body=NORMAL_BODY), autoclose=True)
        self.assertEqual(response.body, NORMAL_BODY)
        # Content-Length shouldn't wait for socket closing
        response = self.request(make_response(NORMAL_BODY))
        self.assertEqual(response.body, NORMAL_BODY)
    
    def test_without_body(self):
        # HEAD and CONNECT shouldn't wait for content body
        for (method,target) in (('HEAD', '/'), ('CONNECT', 'www.google.com:80')):
            response = self.request(Response(), Request(method=method, target=target))
            self.assertEqual(response.body, '')
        # 204 and 304 shouldn't wait for content body
        for code in (204, 304):
            response = self.request(Response(code=code))
            self.assertEqual(response.body, '')
    
    def test_chunked(self):
        # Test chunked body
        response = self.request(make_response(CHUNKED_BODY, chunked=True))
        self.assertEqual(response.body, NORMAL_BODY * 2)
        # Test chunked body (with a tail header)
        response = self.request(make_response(CHUNKED_HEADER % ('Test-Header', 'test value'), chunked=True))
        self.assertTrue('Test-Header' in response.headers, "Test-Header header not found")
        self.assertEqual(response.headers['Test-Header'], 'test value')
        self.assertEqual(response.body, NORMAL_BODY * 2)
    
    def test_closing_early(self):
        # Closing early should raise data error
        self.assertRaises(HTTPDataError, self.request,
            make_response(NORMAL_BODY[:-1], length=len(NORMAL_BODY)),
            autoclose=True)
        # Same with chunked body
        self.assertRaises(HTTPDataError, self.request,
            make_response(CHUNKED_BODY[:-1], chunked=True),
            autoclose=True)
    
    def test_limits(self):
        # Test size limit: no content-length, no content body
        res = Response()
        response = self.request(res, sizelimit=len(res.toString()), autoclose=True)
        self.assertRaises(HTTPLimitError, self.request,
            res, sizelimit=len(res.toString()) - 1)
        # Test size limit: no content-length, with content body
        res = Response(body=NORMAL_BODY)
        response = self.request(res, sizelimit=len(res.toString()) + len(NORMAL_BODY), autoclose=True)
        self.assertRaises(HTTPLimitError, self.request,
            res, sizelimit=len(res.toString()) + len(NORMAL_BODY) - 1)
        # Test size limit: with content-length, no content body
        res = make_response('')
        response = self.request(res, sizelimit=len(res.toString()))
        self.assertRaises(HTTPLimitError, self.request,
            res, sizelimit=len(res.toString()) - 1)
        # Test size limit: with content-length, with content body
        res = make_response(NORMAL_BODY)
        response = self.request(res, sizelimit=len(res.toString()) + len(NORMAL_BODY))
        self.assertRaises(HTTPLimitError, self.request,
            res, sizelimit=len(res.toString()) + len(NORMAL_BODY) - 1)
        # Test body limits with Content-Length
        res = make_response(NORMAL_BODY)
        response = self.request(res, bodylimit=len(NORMAL_BODY))
        self.assertRaises(HTTPLimitError, self.request,
            res, bodylimit=len(NORMAL_BODY) - 1)

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.server.start()
        self.proxy = None
        self.proxy_url = None
    
    def tearDown(self):
        if self.proxy is not None:
            self.proxy.stop()
            self.proxy.join()
            self.proxy = None
        self.server.stop()
        self.server.join()
        self.server = None
    
    def _use_proxy(self):
        self.proxy = ProxyServer()
        self.proxy.start()
        self.proxy_url = "https://%s:%s" % (self.proxy.host, self.proxy.port)
    
    def _make_url(self, path="/"):
        return "%s://%s:%s%s" % (self.server.secure and 'https' or 'http', self.server.host, self.server.port, path)
    
    def request(self, responses, url=None, autoclose=False, timeout=5, sizelimit=None, bodylimit=None, version=(1,1)):
        if not isinstance(responses, (tuple,list)):
            responses = [responses]
        for response in responses:
            self.server.enqueue(response, autoclose=autoclose)
            if self.proxy:
                self.proxy.enqueue(self.server.host, self.server.port)
        if not url:
            url = self._make_url()
        start = time.time()
        try:
            return Agent(timeout=timeout*2, keepalive=False, sizelimit=sizelimit, bodylimit=bodylimit, proxy=self.proxy_url).makeRequest(url, version=version)
        finally:
            self.assertTrue(time.time() - start < timeout, "request took too long")
    
    def test_normal(self):
        response = self.request(make_response(NORMAL_BODY))
        self.assertEqual(response.body, NORMAL_BODY)
        self.assertEqual(response.url, self._make_url())
        self.assertEqual(response.urlchain, [self._make_url()])
    
    def test_redirect(self):
        response = self.request([
            make_response("", code=302, headers={'Location': '/test'}),
            make_response(NORMAL_BODY),
        ])
        self.assertEqual(response.code, 200)
        self.assertEqual(response.body, NORMAL_BODY)
        self.assertEqual(response.url, self._make_url('/test'))
        self.assertEqual(response.urlchain, [self._make_url(), self._make_url('/test')])
    
    def test_secure_url(self):
        self.server.secure = True
        url = self._make_url()
        self.assertTrue(url.startswith('https://'), url)
    
    def test_secure_normal(self):
        self.server.secure = True
        self.test_normal()
    
    def test_secure_redirect(self):
        self.server.secure = True
        self.test_redirect()
    
    def test_proxy_normal(self):
        self._use_proxy()
        self.test_normal()
    
    def test_proxy_redirect(self):
        self._use_proxy()
        self.test_redirect()
    
    def test_proxy_secure_normal(self):
        self._use_proxy()
        self.server.secure = True
        self.test_normal()
    
    def test_proxy_secure_redirect(self):
        self._use_proxy()
        self.server.secure = True
        self.test_redirect()
