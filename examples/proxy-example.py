import gevent.monkey; gevent.monkey.patch_all()
from kitsu.http.client import Agent, Connector
from kitsu.http.request import Request, RequestParser
from kitsu.http.response import Response
import socket
import gevent

def simple_proxy(host='127.0.0.1', port=0):
    server = socket.socket()
    def sendresponse(sock, code, phrase, close=True):
        if close:
            headers = (('Connection', 'close'), ('Content-Length', '0'))
        else:
            headers = ()
        response = Response(code=code, phrase=phrase, headers=headers)
        sock.sendall(response.toString())
        if close:
            sock.shutdown(socket.SHUT_RDWR)
    def passthru(src, dst):
        addr = src.getpeername()
        while True:
            data = src.recv(1024)
            if len(data) > 30:
                print "Received %r" % (data[:30] + '...')
            else:
                print "Received %r" % (data,)
            if not data:
                print "Disconnected from %s:%s" % addr
                try:
                    dst.shutdown(socket.SHUT_WR)
                except:
                    pass
                break
            dst.sendall(data)
    def proxier(client, addr):
        print "Connection from %s:%s" % addr
        parser = RequestParser()
        while True:
            data = client.recv(1024)
            if not data:
                return
            request = parser.parse(data)
            if request:
                request = request[0]
                break
        if request.method != 'CONNECT':
            return sendresponse(client, 405, 'Method Not Allowed')
        if ':' not in request.target:
            return sendresponse(client, 403, 'Forbidden (malformed target)')
        host, port = request.target.split(':', 1)
        try:
            port = int(port)
        except ValueError:
            return sendresponse(client, 403, 'Forbidden (malformed port)')
        try:
            remote = Connector(timeout=5).connect((host, port))
            print "Connected to %s:%s" % (host, port)
        except Exception, e:
            return sendresponse(client, 500, str(e))
        sendresponse(client, 200, 'Connected', close=False)
        gevent.spawn(passthru, remote, client)
        gevent.spawn(passthru, client, remote)
    def accepter():
        while True:
            client, addr = server.accept()
            gevent.spawn(proxier, client, addr)
    server.bind((host, port))
    server.listen(5)
    gevent.spawn(accepter)
    return server.getsockname()

proxyhost, proxyport = simple_proxy()
agent = Agent(proxy="https://%s:%s" % (proxyhost, proxyport), keepalive=True)
print agent.makeRequest('https://www.google.com/translate')
connector = Connector(proxy="https://%s:%s" % (proxyhost, proxyport))
sock = connector.connect(('www.google.com', 80))
sock.sendall(Request(version=(1,0)).toString())
while True:
    data = sock.recv(1024)
    if not data: break
    print "data: %r" % (data,)
