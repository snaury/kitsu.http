import sys
import time
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
        headers['Content-Length'] = str(length or len(body))
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
    
    def tearDown(self):
        self.server.stop()
        self.server.join()
        self.server = None
    
    def _make_url(self, path="/"):
        return "http://%s:%s%s" % (self.server.host, self.server.port, path)
    
    def request(self, responses, url=None, autoclose=False, timeout=5, sizelimit=None, bodylimit=None, version=(1,1)):
        if not isinstance(responses, (tuple,list)):
            responses = [responses]
        for response in responses:
            self.server.enqueue(response, autoclose=autoclose)
        if not url:
            url = self._make_url()
        start = time.time()
        try:
            return Agent(timeout=timeout*2, keepalive=False, sizelimit=sizelimit, bodylimit=bodylimit).makeRequest(url, version=version)
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
