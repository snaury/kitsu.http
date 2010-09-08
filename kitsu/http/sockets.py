import re
import base64
import urlparse
from kitsu.http.errors import *
from kitsu.http.headers import *
from kitsu.http.request import *
from kitsu.http.response import *
from kitsu.http.decoders import *
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

__all__ = ['Client', 'Agent']

class Client(object):
    def __init__(self, sock, sizelimit=None, bodylimit=None, packetsize=4096):
        self.sock = sock
        self.data = ''
        self.sizelimit = sizelimit
        self.bodylimit = bodylimit
        self.packetsize = packetsize
    
    def __del__(self):
        self.close()
    
    def close(self):
        if self.sock is not None:
            self.sock.close()
    
    def detach(self):
        sock, self.sock = self.sock, None
        return sock
    
    def clear(self):
        data, self.data = self.data, ''
        return data
    
    def __recv(self):
        data = self.sock.recv(self.packetsize)
        #print "<- %r" % (data,)
        return data
    
    def __send(self, data):
        #print "-> %r" % (data,)
        return self.sock.sendall(data)
    
    def __sendBody(self, body):
        if body is None:
            return
        if isinstance(body, basestring):
            if not body:
                return
            self.__send(body)
            return
        while True:
            # assume it's a file
            data = body.read(packetsize)
            if not data:
                break
            self.__send(data)
    
    def makeRequest(self, request):
        sizelimit = self.sizelimit
        self.__send(request.toString())
        self.__sendBody(request.body)
        parser = ResponseParser()
        if not self.data:
            self.data = self.__recv()
        while True:
            if not self.data:
                raise HTTPDataError("not enough data for response")
            response = parser.parse(self.data)
            if sizelimit is not None:
                sizelimit -= len(self.data)
            if response:
                self.data = parser.clear()
                if sizelimit is not None:
                    sizelimit += len(self.data)
                    if sizelimit < 0:
                        raise HTTPLimitError()
                assert parser.done
                assert len(response) == 1
                response = response[0]
                break
            if sizelimit is not None and sizelimit <= 0:
                raise HTTPLimitError()
            self.data = self.__recv()
        decoder = CompoundDecoder.from_response(request.method, response)
        if not decoder:
            # response has no body
            response.body = ''
            return response
        response.body = StringIO()
        def process_chunk(chunk):
            if isinstance(chunk, Headers):
                response.headers.update(chunk, merge=True)
            else:
                response.body.write(chunk)
                if self.bodylimit is not None and response.body.tell() > self.bodylimit:
                    raise HTTPLimitError()
        def process_chunks(chunks):
            for chunk in chunks:
                process_chunk(chunk)
        if not self.data:
            self.data = self.__recv()
        while True:
            if not self.data:
                break
            process_chunks(decoder.parse(self.data))
            if sizelimit is not None:
                sizelimit -= len(self.data)
            if decoder.done:
                break
            if sizelimit is not None and sizelimit < 0:
                raise HTTPLimitError()
            self.data = self.__recv()
        process_chunks(decoder.finish())
        self.data = decoder.clear()
        if sizelimit is not None:
            sizelimit += len(self.data)
            if sizelimit < 0:
                raise HTTPLimitError()
        response.body = response.body.getvalue()
        return response

class HTTPSProxyClient(object):
    __slots__ = ('__sock', '__headers')
    
    def __init__(self, sock, headers=()):
        self.__sock = sock
        self.__headers = Headers(headers)
    
    def __getattr__(self, name):
        return getattr(self.__sock, name)
    
    def __setattr__(self, name, value):
        if name in self.__slots__:
            return object.__setattr__(self, name, value)
        return setattr(self.__sock, name, value)
    
    def __delattr__(self, name):
        if name in self.__slots__:
            return object.__delattr__(self, name, value)
        return delattr(self.__sock, name, value)
    
    def __readline(self, limit=65536):
        """Read a line being careful not to read more than needed"""
        s = StringIO()
        while True:
            c = self.__sock.recv(1)
            if not c:
                break
            s.write(c)
            if c == '\n':
                break
            if s.tell() >= limit:
                break
        return s.getvalue()
    
    def connect(self, address):
        host, port = address
        target = '%s:%s' % (host, port)
        request = Request(method='CONNECT', target=target)
        # The 'Host' header is not strictly needed,
        # it's only added here for consistency
        request.headers['Host'] = target
        request.headers.update(self.__headers)
        self.__sock.sendall(request.toString())
        limit = 65536
        parser = RequestParser()
        while True:
            data = self.__readline(limit)
            if not data:
                raise HTTPDataError("not enough data for response")
            limit -= len(data)
            response = parser.parse(data)
            if response.done:
                data = parser.clear()
                assert not data
                break
            if limit <= 0:
                raise HTTPLimitError("CONNECT: response too big")
        if response.code != 200:
            raise HTTPError("CONNECT failed: %d %s" % (response.code, response.phrase))
    
    def connect_ex(self, *args, **kwargs):
        raise NotImplemented

def _default_gethostbyname(hostname):
    import socket
    try:
        return socket.gethostbyname(hostname)
    except socket.error, e:
        raise HTTPDNSError("%r: %s" % (hostname, e))

def _default_gethostbyaddr(ipaddr):
    import socket
    try:
        return socket.gethostbyaddr(ipaddr)
    except socket.error, e:
        raise HTTPDNSError("%r: %s" % (hostname, e))

def _default_create_connection(address, timeout=None):
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    if timeout is not None:
        sock.settimeout(timeout)
    sock.connect(address)
    return sock

def _default_wrap_ssl(sock, *args, **kwargs):
    try:
        from ssl import wrap_socket
    except ImportError:
        from socket import ssl as wrap_socket
    return wrap_socket(sock, *args, **kwargs)

def _parse_netloc(netloc, default_port=None):
    index = netloc.find(':')
    if index >= 0:
        host, port = netloc[:index], netloc[index+1:]
        try:
            port = int(port)
        except ValueError:
            port = default_port
    else:
        host, port = netloc, default_port
    return host, port

def _parse_uri(uri):
    if '://' not in uri:
        uri = 'http://' + uri
    scheme, netloc, path, query, fragment = urlparse.urlsplit(uri)
    if not netloc and path.startswith('//'):
        # urlsplit ignores netloc for unknown schemes
        path = path[2:]
        index = path.find('/')
        if index >= 0:
            netloc, path = path[:index], path[index:]
        else:
            netloc, path = path, ''
    # split username:password if any
    index = netloc.find('@')
    if index >= 0:
        auth, netloc = netloc[:index], netloc[index+1:]
    else:
        auth = ''
    if query:
        path = path + '?' + query
    return scheme, auth, netloc, path, fragment

def _make_uri(scheme, auth, netloc, path='', fragment=''):
    uri = scheme + '://'
    if auth and netloc:
        uri += auth + '@' + netloc
    else:
        uri += auth or netloc
    if path:
        uri += path
    if fragment:
        uri += '#' + fragment
    return uri

class Agent(object):
    def __init__(self, proxy=None, headers=(), timeout=30, keepalive=False, sizelimit=None, bodylimit=None, redirectlimit=20, gethostbyname=_default_gethostbyname, gethostbyaddr=_default_gethostbyaddr, create_connection=_default_create_connection, wrap_ssl=_default_wrap_ssl):
        self.proxy = proxy
        self.headers = Headers(headers)
        self.timeout = timeout
        self.keepalive = keepalive
        self.sizelimit = sizelimit
        self.bodylimit = bodylimit
        self.redirectlimit = redirectlimit
        self.__gethostbyname = gethostbyname
        self.__gethostbyaddr = gethostbyaddr
        self.__create_connection = create_connection
        self.__wrap_ssl = wrap_ssl
        self.__current_address = None
        self.__current_client = None
    
    def close(self):
        self.__current_address = None
        if self.__current_client is not None:
            self.__current_client.close()
            self.__current_client = None
    
    def __makeRequest(self, url, method='GET', version=(1, 1), headers=(), body=None, referer=None, keyfile=None, certfile=None):
        scheme, auth, netloc, path, fragment = _parse_uri(url)
        scheme = scheme.lower()
        if scheme not in ('http', 'https'):
            raise HTTPError("Unsupported scheme %r: %s" % (scheme, url))
        request = Request(method=method, target=path or '/', version=version, headers=headers, body=body)
        if auth:
            auth = re.sub(r"\s", "", base64.encodestring(auth))
            request.headers['Authorization'] = 'Basic %s' % auth
        if netloc:
            request.headers['Host'] = netloc
        if referer:
            request.headers['Referer'] = referer
        if self.proxy:
            proxytype, proxyauth, proxynetloc, proxypath, proxyfragment = _parseProxy(self.proxy)
            proxytype = proxytype.lower()
            if proxytype not in ('http', 'https'):
                raise HTTPError("Unsupported proxy type %r" % (proxytype,))
            proxyheaders = Headers()
            if proxyauth:
                proxyauth = re.sub(r"\s", "", base64.encodestring(proxyauth))
                proxyheaders['Proxy-Authorization'] = 'Basic %s' % proxyauth
            address = ((proxyscheme, proxynetloc), (scheme, netloc))
            if 'https' not in (scheme, proxytype):
                request.target = url
                request.headers.update(proxyheaders)
        else:
            address = ((scheme, netloc),)
        if self.__current_address != address:
            self.close()
        if self.__current_client is None:
            tscheme, tnetloc = address[0]
            sock = self.__create_connection(_parse_netloc(tnetloc, tscheme == 'https' and 443 or 80), self.timeout)
            if self.proxy and 'https' in (scheme, proxytype):
                tscheme, tnetloc = address[1]
                sock = HTTPSProxyClient(sock, proxyheaders)
                sock.connect(_parse_netloc(tnetloc, tscheme == 'https' and 443 or 80))
            if scheme == 'https':
                sock = self.__wrap_ssl(sock, keyfile=keyfile, certfile=certfile)
            client = self.__current_client = Client(sock, sizelimit=self.sizelimit, bodylimit=self.bodylimit)
            self.__current_address = address
        else:
            client = self.__current_client
            client.sizelimit = self.sizelimit
            client.bodylimit = self.bodylimit
        return client.makeRequest(request)
    
    def makeRequest(self, url, **kwargs):
        url = url.strip()
        return self.__makeRequest(url, **kwargs)
