import sys
import time
import socket
import select
import threading
from kitsu.http.agent import *
from kitsu.http.errors import *
from kitsu.http.request import *
from kitsu.http.response import *

class Server(threading.Thread):
    def __init__(self, host='127.0.0.1', port=0):
        threading.Thread.__init__(self)
        self.sock = socket.socket()
        self.sock.bind((host, port))
        self.sock.listen(1)
        self.host, self.port = self.sock.getsockname()
        self.daemon = True
        self.responses = []
        self.deadsockets = []
    
    def enqueue(self, response, autoclose=False):
        self.responses.append((response, autoclose))
    
    def run(self):
        try:
            while True:
                sock, addr = self.sock.accept()
                autoclose = True
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
                    assert self.responses, "no response in server thread, likely a bug"
                    response, autoclose = self.responses.pop(0)
                    print "%s %s -> %d %s%s" % (request.method, request.target, response.code, response.phrase, response.body and " (%d bytes)" % len(response.body) or "")
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

server = Server()
server.start()

def test_response(response, method='GET', target='/', autoclose=False, timeout=5, bodylimit=None):
    sock = socket.socket()
    sock.settimeout(timeout * 2)
    server.enqueue(response, autoclose=autoclose)
    sock.connect((server.host, server.port))
    start = time.time()
    try:
        return Client(sock, bodylimit=bodylimit).makeRequest(Request(method=method, target=target))
    finally:
        assert time.time() - start < timeout, "request took too long, likely a bug"

def test_http_error(response, text, **kwargs):
    try:
        test_response(response, **kwargs)
    except Exception, e:
        assert isinstance(e, HTTPError) and str(e) == text, "expected HTTPError(%r), got %r" % (text, e)
    else:
        assert False, "expected HTTPError(%r)" % (text,)

def test_not_enough_data(response, autoclose=True):
    test_http_error(response, 'not enough data', autoclose=autoclose)

def test_too_much_data(response, bodylimit=None):
    test_http_error(response, 'too much data', bodylimit=bodylimit)

# Test normal body
normal_body = "Hello world"
response = Response(body=normal_body)
response = test_response(response, autoclose=True)
assert response.body == normal_body
# Content-Length should work without remote closing socket
response = Response(body=normal_body)
response.headers['Content-Length'] = str(len(normal_body))
response = test_response(response)
assert response.body == normal_body
# HEAD and CONNECT shouldn't wait for any content
for (method,target) in (('HEAD', '/'), ('CONNECT', 'www.google.com:80')):
    response = Response()
    response = test_response(response, method=method, target=target)
    assert not response.body
# 204 and 304 shouldn't wait for any content
for code in (204, 304):
    response = Response(code=code)
    response = test_response(response)
    assert not response.body

# Test chunked body
chunked_body = ("""\
%(size)X
%(chunk)s
%(size)X; test=1
%(chunk)s
0

""" % dict(size=len(normal_body), chunk=normal_body)).replace("\n", "\r\n")
response = Response(body=chunked_body)
response.headers['Transfer-Encoding'] = 'chunked'
response = test_response(response)
assert response.body == normal_body * 2

# Test chunked body (with headers)
header_name = 'Test-Header'
header_value = 'test'
chunked_body_with_headers = ("""\
%(size)X
%(chunk)s
%(size)X; test=1
%(chunk)s
0
%(name)s: %(value)s

""" % dict(size=len(normal_body), chunk=normal_body, name=header_name, value=header_value)).replace("\n", "\r\n")
response = Response(body=chunked_body_with_headers)
response.headers['Transfer-Encoding'] = 'chunked'
response = test_response(response)
assert response.headers.get(header_name) == header_value
assert response.body == normal_body * 2

# Closing too early should raise errors
response = Response(body=normal_body[:-1])
response.headers['Content-Length'] = str(len(normal_body))
test_not_enough_data(response)
# And also with chunked
response = Response(body=chunked_body[:-1])
response.headers['Transfer-Encoding'] = 'chunked'
test_not_enough_data(response)
# Don't forget partial headers too
response = Response(body=chunked_body_with_headers[:-1])
response.headers['Transfer-Encoding'] = 'chunked'
test_not_enough_data(response)

# Shouldn't raise on exact limit match
response = Response(body=normal_body)
response.headers['Content-Length'] = str(len(normal_body))
test_response(response, bodylimit=len(normal_body))
# Test body limit
response = Response(body=normal_body)
response.headers['Content-Length'] = str(len(normal_body))
test_too_much_data(response, bodylimit=len(normal_body)-1)
