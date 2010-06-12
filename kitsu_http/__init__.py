# Copyright (c) 2010 Alexey Borzenkov.
# See LICENSE for details.

from urlparse import urlsplit, urljoin
from twisted.python.failure import Failure
from twisted.internet.protocol import Protocol, ClientFactory, ClientCreator
from twisted.internet.defer import fail, Deferred

__all__ = [
    'Headers',
    'Request',
    'Response',
    'Agent',
    'TunnelCreator',
]

_canonicalHeaderParts = { 'www' : 'WWW' }
def _canonicalHeaderName(name):
    def canonical(part):
        return _canonicalHeaderParts.get(part) or part.capitalize()
    return '-'.join(canonical(part.lower()) for part in name.split('-'))

def _parseProxy(proxy):
    if not proxy:
        return proxy
    try:
        if isinstance(proxy, basestring):
            proxyhost, proxyport = proxy.split(':', 1)
        else:
            proxyhost, proxyport = proxy
        if isinstance(proxyport, basestring):
            proxyport = int(proxyport)
    except ValueError:
        raise HTTPError("proxy must be either in 'host:port' or (host, port) format")
    return (proxyhost, proxyport)

class HTTPError(Exception):
    pass

class HTTPTimeout(HTTPError):
    pass

HeadersBase = dict
class Headers(HeadersBase):
    _partialHeader = None
    
    def __init__(self, data=()):
        HeadersBase.__init__(self)
        if data:
            self.update(data)
    
    def __getitem__(self, name):
        return HeadersBase.__getitem__(self, name.lower())
    
    def __setitem__(self, name, value):
        return HeadersBase.__setitem__(self, name.lower(), value)
    
    def __delitem__(self, name):
        return HeadersBase.__delitem__(self, name)
    
    def __contains__(self, name):
        return HeadersBase.__contains__(self, name.lower())
    
    def has_key(self, name):
        return HeadersBase.has_key(self, name.lower())
    
    def get(self, name, *args):
        return HeadersBase.get(self, name.lower(), *args)
    
    def pop(self, name, *args):
        return HeadersBase.pop(self, name.lower(), *args)
    
    def setdefault(self, name, *args):
        return HeadersBase.setdefault(self, name.lower(), *args)
    
    def update(self, data=()):
        if hasattr(data, 'iteritems'):
            data = data.iteritems()
        for name, value in data:
            self[name] = value
    
    def add(self, name, value):
        values = self.get(name)
        if isinstance(values, list):
            values.append(value)
        elif isinstance(values, basestring):
            values = [values, value]
            self[name] = values
        else:
            self[name] = value
    
    def toLines(self, lines=None):
        if lines is None:
            lines = []
        for name, values in self.iteritems():
            name = _canonicalHeaderName(name)
            if not isinstance(values, list):
                values = [values]
            for value in values:
                lines.append("%s: %s\r\n" % (name, value))
        return lines
    
    def flushPartialHeader(self):
        if self._partialHeader:
            header = ''.join(self._partialHeader)
            del self._partialHeader
            parts = header.split(':', 1)
            if len(parts) != 2:
                raise HTTPError("header must be in 'name: value' format")
            name = parts[0].rstrip()
            value = parts[1].strip()
            if not name:
                raise HTTPError("header must be in 'name: value' format")
            self.add(name, value)
    
    def parseLine(self, line):
        if not line or not line[0] in ' \t':
            self.flushPartialHeader()
            if line:
                self._partialHeader = [line]
        else:
            if self._partialHeader:
                self._partialHeader.append(line)
        return line and True or False

class Request(object):
    """
    HTTP Request
    """
    
    _parserState = 'COMMAND'
    
    def __init__(self, method="GET", target="/", version=(1,1), headers=(), body=None):
        self.method = method
        self.target = target
        self.version = version
        self.headers = Headers(headers)
        self.body = body
    
    def _writeHeaders(self, transport):
        lines = ["%s %s HTTP/%d.%d\r\n" % (self.method, self.target, self.version[0], self.version[1])]
        self.headers.toLines(lines)
        lines.append("\r\n")
        transport.writeSequence(lines)
    
    def writeTo(self, transport):
        self._writeHeaders(transport)
        if self.body:
            transport.write(self.body)
    
    def _parseCommand(self, line):
        parts = line.split(None, 2)
        if len(parts) != 3:
            raise HTTPError("request must be in 'METHOD target HTTP/n.n' format")
        method, target, version = parts
        if not version.startswith('HTTP/'):
            raise HTTPError("protocol must be HTTP")
        version = version[5:].split('.')
        if len(version) != 2:
            raise HTTPError("invalid version")
        try:
            version = (int(version[0]), int(version[1]))
        except ValueError:
            raise HTTPError("invalid version")
        self.method = method
        self.target = target
        self.version = version
    
    def parseLine(self, line):
        if self._parserState == 'COMMAND':
            if not line:
                # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html
                # We just ignore all empty lines for maximum compatibility
                return True
            self._parseCommand(line)
            self._parserState = 'HEADERS'
        elif self._parserState == 'HEADERS':
            if not self.headers.parseLine(line):
                self._parserState = 'DONE'
        return line and True or False

class Response(object):
    """
    HTTP Response
    """
    
    _parserState = 'STATUS'
    
    def __init__(self, version=(1,1), code=None, phrase=None, headers=(), body=None):
        self.version = version
        self.code = code
        self.phrase = phrase
        self.headers = Headers(headers)
        self.body = body
    
    def _writeHeaders(self, transport):
        lines = ["HTTP/%d.%d %d %s" % (self.version[0], self.version[1], self.code, self.phrase)]
        self.headers.toLines(lines)
        lines.append("\r\n")
        transport.writeSequence(lines)
    
    def writeTo(self, transport):
        self._writeHeaders(transport)
        if self.body:
            transport.write(self.body)
    
    def _parseStatus(self, line):
        parts = line.split(None, 2)
        if len(parts) not in (2, 3):
            raise HTTPError("response must be in 'HTTP/n.n status message' format")
        version = parts[0]
        code = parts[1]
        phrase = len(parts) >= 3 and parts[2] or ""
        if not version.startswith('HTTP/'):
            raise HTTPError("protocol must be HTTP")
        version = version[5:].split('.')
        if len(version) != 2:
            raise HTTPError("invalid version")
        try:
            version = (int(version[0]), int(version[1]))
        except ValueError:
            raise HTTPError("invalid version")
        try:
            code = int(code)
        except ValueError:
            raise HTTPError("status code must be a number")
        self.version = version
        self.code = code
        self.phrase = phrase
    
    def parseLine(self, line):
        if self._parserState == 'STATUS':
            if not line:
                # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html
                # We just ignore all empty lines for maximum compatibility
                return True
            self._parseStatus(line)
            self._parserState = 'HEADERS'
        elif self._parserState == 'HEADERS':
            if not self.headers.parseLine(line):
                self._parserState = 'DONE'
        return line and True or False

class Parser(object):
    """
    Parser
    """
    
    done = False
    cache = ''
    
    def clear(self):
        data, self.cache = self.cache, ''
        return data
    
    def prepend(self, data):
        if data:
            self.cache = data + self.cache
    
    def append(self, data):
        if data:
            self.cache = self.cache + data
    
    def parse(self, data):
        if data:
            self.cache += data
        if self.done:
            return []
        output = []
        while self.cache and not self.done:
            data, self.cache = self.cache, ''
            result = self.parseRaw(data)
            if result is None: # force wait for more data
                break
            output.extend(result)
        return output
    
    def finish(self):
        self.done = True
        return []
    
    def parseRaw(self, data):
        raise NotImplementedError

class LineParser(Parser):
    """
    Line Parser
    """
    
    linemode = True
    delimiter = '\r\n'
    
    def parseRaw(self, data):
        if self.linemode:
            pos = data.find(self.delimiter)
            if pos < 0:
                self.prepend(data)
                return None
            line, data = data[:pos], data[pos+len(self.delimiter):]
            self.prepend(data)
            return self.parseLine(line)
        else:
            return self.parseData(data)
    
    def setLineMode(self, extra=''):
        if extra:
            self.prepend(extra)
        self.linemode = True
    
    def setDataMode(self, extra=''):
        if extra:
            self.prepend(extra)
        self.linemode = False
    
    def parseLine(self, line):
        raise NotImplementedError
    
    def parseData(self, data):
        raise NotImplementedError

class RequestParser(LineParser):
    """
    HTTP Request Parser
    """
    
    def __init__(self):
        self.request = Request()
    
    def parseLine(self, line):
        if not self.request.parseLine(line):
            self.done = True
            return [self.request]
        return []

class ResponseParser(LineParser):
    """
    HTTP Response Parser
    """
    
    def __init__(self):
        self.response = Response()
    
    def parseLine(self, line):
        if not self.response.parseLine(line):
            self.done = True
            return [self.response]
        return []

class ChunkedDecoder(LineParser):
    def __init__(self):
        self.length = None
        self.extensions = None
        self.headers = None
    
    def parseLine(self, line):
        if self.headers is not None:
            # We are reading the trailer
            if not self.headers.parseLine(line):
                self.done = True
                return [self.headers]
        elif self.length == 0:
            assert not line, "Chunk data must end with '\\r\\n'"
            self.length = None
        else:
            # We must be reading chunk header
            parts = line.split(';', 1)
            length = int(parts[0],16)
            if len(parts) >= 2:
                extensions = parts[0].strip()
            else:
                extensions = None
            self.length = length
            self.extensions = extensions
            if self.length == 0:
                # Start reading trailer headers
                self.headers = Headers()
            else:
                # Start reading chunk data
                self.setDataMode()
        return []
    
    def parseData(self, data):
        body, data = data[:self.length], data[self.length:]
        self.length -= len(body)
        if self.length == 0:
            self.setLineMode(data)
        return [body]

class IdentityDecoder(Parser):
    def __init__(self, length=None):
        self.length = length
    
    def parseRaw(self, data):
        if self.length is None:
            body, data = data, ''
        elif self.length:
            body, data = data[:self.length], data[self.length:]
            self.length -= len(body)
            if self.length == 0:
                self.done = True
        else:
            body = ''
        if data:
            self.prepend(data)
        if body:
            return [body]
        return []

class DeflateDecoder(Parser):
    def __init__(self):
        from zlib import decompressobj
        self.obj = decompressobj()
    
    def parseRaw(self, data):
        data = self.obj.decompress(data)
        if data:
            return [data]
        return []
    
    def finish(self):
        if not self.done:
            self.done = True
            data = self.obj.flush()
            self.prepend(self.obj.unused_data)
            self.obj = None
            if data:
                return [data]
        return []

class Client(Protocol):
    """
    HTTP Client
    """
    
    __buffer = ''
    
    def __init__(self):
        self.__reset()
    
    def __reset(self):
        self.result = None
        self.parser = None
        self.request = None
        self.response = None
        self.decoders = None
        self.readingChunked = False
        self.readingUntilClosed = False
        self.bodySizeLimit = None
    
    def __succeeded(self, response):
        result = self.result
        self.__reset()
        if result is not None:
            result.callback(response)
    
    def __failed(self, failure):
        result = self.result
        self.__reset()
        if result is not None:
            result.errback(failure)
    
    def clearBuffer(self):
        data, self.__buffer = self.__buffer, ''
        return data
    
    def cancelRequest(self):
        data = self.clearBuffer()
        self.__reset()
        self.__buffer = data
    
    def makeRequest(self, request):
        try:
            if self.result is not None:
                raise HTTPError("Cannot make new requests while another one in progress")
        except:
            return fail(Failure())
        
        self.result = result = Deferred()
        try:
            self.parser = ResponseParser()
            self.request = request
            self.request.writeTo(self.transport)
            if self.__buffer:
                self.dataReceived(self.clearBuffer())
        except:
            self.__failed(Failure())
        return result
    
    def decodeBody(self, data=''):
        if not self.decoders:
            return ''
        if data:
            current = [data]
        else:
            current = []
        prevdone = False
        if not current:
            # If we are called without data then finish the chain
            prevdone = True
        for decoder in self.decoders:
            output = []
            for chunk in current:
                output.extend(decoder.parse(chunk))
            if output and isinstance(decoder, ChunkedDecoder):
                # We might have trailer headers in the output
                if isinstance(output[-1], Headers):
                    headers = output.pop()
                    for name, values in headers.iteritems():
                        if not isinstance(values, list):
                            values = [values]
                        for value in values:
                            self.response.headers.add(name, value)
            if prevdone:
                output.extend(decoder.finish())
            current = output
            prevdone = decoder.done
        return ''.join(current)
    
    def dataReceived(self, data):
        try:
            if data and self.parser:
                response = self.parser.parse(data)
                if response:
                    assert len(response) == 1
                    response = response[0]
                    assert self.parser.done
                    self.__buffer = self.parser.clear()
                    self.parser = None
                    self.gotResponse(response)
                    data = self.clearBuffer()
                else:
                    data = ''
            if data and self.decoders:
                body = self.decodeBody(data)
                if self.decoders[0].done:
                    self.__buffer = self.decoders[0].clear()
                    self.gotBody(body, True)
                    data = self.clearBuffer()
                else:
                    self.gotBody(body)
                    data = ''
            self.__buffer += data
        except:
            self.__failed(Failure())
    
    def connectionLost(self, failure):
        if self.result is not None:
            if self.response and self.readingUntilClosed:
                # We were reading data up to the end
                self.gotBody(self.decodeBody(), True)
            else:
                # We were either parsing or reading data
                self.__failed(failure)
    
    responseCodesWithoutBody = frozenset((204, 304))
    requestMethodsWithoutBody = frozenset(('HEAD', 'CONNECT'))
    def gotResponse(self, response):
        self.response = response
        
        # process Content-Length
        contentLength = response.headers.get('Content-Length')
        if isinstance(contentLength, list):
            contentLength = contentLength[0]
        if contentLength:
            contentLength = int(contentLength)
        else:
            contentLength = None
        if self.request.method in self.requestMethodsWithoutBody:
            contentLength = 0
        if contentLength is None and response.code in self.responseCodesWithoutBody:
            contentLength = 0
        if contentLength == 0:
            # There is no body, so we can succeed right now
            self.__succeeded(response)
            return
        
        # process Transfer-Encoding
        encodings = response.headers.get('Transfer-Encoding')
        if encodings is None:
            encodings = ['identity']
        elif not isinstance(encodings, list):
            encodings = [encodings]
        encodings = ', '.join(encodings)
        encodings = [encoding.strip() for encoding in encodings.split(',')]
        encodings.reverse()
        decoders = []
        baseDecoderFound = False
        for encoding in encodings:
            encoding = encoding.split(';', 1)[0] # strip parameters
            encoding = encoding.strip().lower()
            if encoding == 'chunked':
                assert not decoders, "Transfer-Encoding 'chunked' must be the last in chain"
                decoders.append(ChunkedDecoder())
                self.readingChunked = True
                baseDecoderFound = True
            elif encoding == 'identity':
                assert not decoders, "Transfer-Encoding 'identity' must be the last in chain"
                continue
            elif encoding == 'deflate':
                decoders.append(DeflateDecoder())
            else:
                # TODO: implement gzip?
                raise HTTPError("Don't know how to decode Transfer-Encoding %r" % (encoding,))
        if not baseDecoderFound:
            decoders.insert(0, IdentityDecoder(contentLength))
            self.readingUntilClosed = contentLength is None
        self.decoders = decoders
    
    def gotBody(self, body, finished=False):
        if self.response.body is None:
            self.response.body = ''
        self.response.body += body
        if self.bodySizeLimit is not None and len(self.response.body) > self.bodySizeLimit:
            self.__failed(HTTPError("Response body size exceeded the limit"))
        if finished:
            self.__succeeded(self.response)

class AgentArgs(object):
    def __init__(self, url, method, version, headers, body, referer, proxy, proxyheaders, proxytype):
        self.url = url
        self.method = method
        self.version = version
        self.headers = headers
        self.body = body
        self.referer = referer
        
        self.proxy = _parseProxy(proxy)
        self.proxyheaders = proxyheaders
        self.proxytype = proxytype
        
        # Split url into parts and determine host, port and target
        self.scheme, self.netloc, self.path, self.query, self.fragment = urlsplit(self.url)
        if ':' in self.netloc:
            host, port = self.netloc.split(':', 1)
            port = int(port)
        else:
            host = self.netloc
            if self.scheme == 'https':
                port = 443
            else:
                port = 80
        self.netloc_addr = (host, port)
        if self.proxy:
            host, port = self.proxy
        self.host = host
        self.port = port
        self.target = self.path
        if not self.target.startswith('/'):
            self.target = '/' + self.target
        if self.query:
            self.target = self.target + '?' + self.query
        self.request = None
        self.tunneling = False
    
    def makeRequest(self):
        request = Request(self.method, self.target, self.version, self.headers, self.body)
        if self.body or self.method != 'GET':
            request.headers['Content-Length'] = "%d" % len(self.body or '')
        if self.referer:
            scheme, netloc, path, query, fragment = urlsplit(self.referer)
            if scheme != 'https' or self.scheme == scheme:
                # Add referer unless moving away from https
                request.headers['Referer'] = self.referer
        if self.proxy:
            if self.scheme == 'https' or self.proxytype == 'https':
                if not self.tunneling:
                    # We must use proxy to connect to netloc
                    request.method = 'CONNECT'
                    request.target = "%s:%d" % self.netloc_addr
                    request.headers = Headers() # Don't disclose request headers to the proxy
                    request.body = None # Don't send any body yet
                # If we are using a tunnel we should make a regular request
            else:
                # Use proxy to retrieve target url
                request.target = self.url
            if not self.tunneling:
                headers = Headers(self.proxyheaders)
                for name, values in headers.iteritems():
                    # Should we really use Headers.add?
                    request.headers[name] = values
        if 'Host' not in request.headers:
            request.headers['Host'] = self.netloc
        self.request = request
        return request

class Agent(object):
    result = None
    args = None
    client = None
    timeout = 30
    timeoutCall = None
    redirectCount = 0
    redirectLimit = 20
    followRedirects = True
    closeOnSuccess = True
    closeOnFailure = True
    bodySizeLimit = None
    
    def __init__(self, reactor, contextFactory=None):
        self.reactor = reactor
        self.contextFactory = contextFactory
    
    def close(self):
        self.__reset(True)
    
    def __reset(self, close=False):
        self.result = None
        if close:
            self.args = None
            self.__closeClient()
        elif self.client is not None:
            try:
                self.client.cancelRequest()
            except:
                pass
        self.__stopTimeout()
        if self.redirectCount:
            del self.redirectCount
    
    def __succeeded(self, response):
        result = self.result
        self.__reset(self.closeOnSuccess)
        if result is not None:
            result.callback(response)
    
    def __failed(self, failure):
        result = self.result
        self.__reset(self.closeOnFailure)
        if result is not None:
            result.errback(failure)
    
    def __timedOut(self, exc=None):
        if exc is None:
            exc = HTTPTimeout("Request timed out")
        self.__failed(Failure(exc))
    
    def __closeClient(self):
        if self.client is not None:
            try:
                self.client.transport.loseConnection()
            except:
                pass
            self.client = None
    
    def __stopTimeout(self):
        if self.timeoutCall is not None:
            try:
                self.timeoutCall.cancel()
            except:
                pass
            self.timeoutCall = None
    
    def __startTimeout(self, exc=None):
        self.__stopTimeout()
        self.timeoutCall = self.reactor.callLater(self.timeout, self.__timedOut, exc)
    
    def __startRequest(self):
        self.__startTimeout()
        self.client.bodySizeLimit = self.bodySizeLimit
        r = self.client.makeRequest(self.args.makeRequest())
        r.addCallback(self.gotResponse).addErrback(self.__failed)
    
    def getContextFactory(self):
        if self.contextFactory is None:
            from twisted.internet import ssl
            self.contextFactory = ssl.ClientContextFactory()
        return self.contextFactory
    
    def __makeRequest(self, url, method, version, headers, body, referer, proxy, proxyheaders, proxytype):
        assert self.result is not None
        oldargs, newargs = self.args, AgentArgs(url=url, method=method, version=version, headers=headers, body=body, referer=referer, proxy=proxy, proxyheaders=proxyheaders, proxytype=proxytype)
        self.args = newargs
        if self.client is not None:
            reuse = False
            if oldargs is not None and (oldargs.host, oldargs.port) == (newargs.host, newargs.port):
                # We are connecting to the same host, so maybe we can reuse the client
                if oldargs.tunneling:
                    # Reuse only if netloc didn't change (otherwise it might be a different server)
                    reuse = newargs.netloc_addr == oldargs.netloc_addr
                else:
                    reuse = True
                if reuse:
                    newargs.tunneling = oldargs.tunneling
                    self.__startRequest()
                    return
            self.__closeClient()
        c = ClientCreator(self.reactor, Client)
        if newargs.scheme == 'https' and not newargs.proxy:
            d = c.connectSSL(newargs.host, newargs.port, contextFactory=self.getContextFactory())
        else:
            d = c.connectTCP(newargs.host, newargs.port)
        d.addCallback(self.gotProtocol).addErrback(self.__failed)
    
    def makeRequest(self, url, method='GET', version=(1,1), headers=(), body=None, referer=None, proxy=None, proxyheaders=(), proxytype='http'):
        try:
            if self.result is not None:
                raise HTTPError("Cannot make new requests while another one in progress")
        except:
            return fail(Failure())
        
        self.result = result = Deferred()
        try:
            self.__makeRequest(url=url, method=method, version=version, headers=headers, body=body, referer=referer, proxy=proxy, proxyheaders=proxyheaders, proxytype=proxytype)
        except:
            self.__failed(Failure())
        return result
    
    def gotProtocol(self, protocol):
        self.client = protocol
        self.__startRequest()
    
    def gotResponse(self, response):
        self.__stopTimeout()
        keepalive = response.version >= (1,1)
        if 'Connection' in response.headers:
            # Connection header(s) might override the default
            values = response.headers['Connection']
            if isinstance(values, list):
                values = ', '.join(values)
            values = [value.strip().lower() for value in values.split(',')]
            if 'keep-alive' in values:
                keepalive = True
            if 'close' in values:
                keepalive = False
        if not keepalive:
            # Close connection if Keep-Alive is not supported
            self.__closeClient()
        if self.followRedirects and response.code in (301, 302, 303, 307):
            # Process redirects
            self.redirectCount += 1
            if self.redirectCount > self.redirectLimit:
                self.__failed(HTTPError("Too many redirects"))
                return
            url = response.headers.get('Location')
            if url and isinstance(url, list):
                url = url[0]
            if url:
                url = urljoin(self.args.url, url)
                self.__makeRequest(url=url, method=self.args.method, version=self.args.version, headers=self.args.headers, body=self.args.body, referer=self.args.url, proxy=self.args.proxy, proxyheaders=self.args.proxyheaders, proxytype=self.args.proxytype)
                return
        if response.code == 200 and self.args.request.method == 'CONNECT':
            # Our tunnel has connected, now we can make a real request
            if self.args.scheme == 'https':
                # But for https we need to start TLS first
                assert not self.client.clearBuffer(), "Server sent some data before we could start TLS"
                self.client.transport.startTLS(self.getContextFactory())
                self.client.transport.startWriting()
            self.args.tunneling = True
            self.__startRequest()
            return
        response.url = self.args.url
        self.__succeeded(response)

class TunnelProtocol(Protocol):
    __buffer = ''
    client = None
    target = None
    timeoutCall = None
    disconnected = None
    
    def gotTimeout(self):
        self.timeoutCall = None
        self.__failed(HTTPTimeout("Tunnel connection timed out"))
    
    def startTimeout(self):
        self.cancelTimeout()
        self.timeoutCall = self.factory.reactor.callLater(self.factory.timeout, self.gotTimeout)
    
    def cancelTimeout(self):
        if self.timeoutCall is not None:
            self.timeoutCall.cancel()
            self.timeoutCall = None
    
    def __succeeded(self, tunnel):
        self.cancelTimeout()
        self.client = None
        self.factory.gotTunnel(self)
    
    def __failed(self, failure):
        self.cancelTimeout()
        self.client = None
        self.transport.loseConnection()
        self.factory.gotError(failure)
    
    def clearBuffer(self):
        data, self.__buffer = self.__buffer, ''
        return data
    
    def connectionMade(self):
        self.startTimeout()
        try:
            netloc = '%s:%d' % (self.factory.host, self.factory.port)
            request = Request(method='CONNECT', target=netloc, headers=self.factory.headers)
            request.headers['Host'] = netloc
            self.client = Client()
            self.bodySizeLimit = 16*1024 # is 16k enough for an error message?
            self.client.makeConnection(self.transport)
            d = self.client.makeRequest(request)
            d.addCallback(self.gotResponse)
            d.addErrback(self.__failed)
        except:
            self.__failed(Failure())
    
    def connectionLost(self, failure):
        if self.target is not None:
            self.target.connectionLost(failure)
        if self.client is not None:
            self.client.connectionLost(failure)
        self.disconnected = failure
    
    def dataReceived(self, data):
        if self.target is not None:
            self.target.dataReceived(data)
            return
        if self.client is not None:
            self.client.dataReceived(data)
            return
        self.__buffer += data
    
    def gotResponse(self, response):
        # Exceptions here will be caught by self.__failed
        if response.code != 200:
            raise HTTPError("Expected '200 Connection established', got '%d %s'" % (response.code, response.phrase))
        self.__buffer += self.client.clearBuffer()
        self.__succeeded(self)
    
    def startTunneling(self, target):
        if self.factory.contextFactory is not None:
            assert not self.__buffer, "Server sent some data before we could start TLS"
            self.transport.startTLS(self.factory.contextFactory)
            self.transport.startWriting()
        self.target = target
        self.target.makeConnection(self.transport)
        if self.__buffer:
            self.target.dataReceived(self.clearBuffer())
        if self.disconnected is not None:
            self.target.connectionLost(self.disconnected)

class TunnelFactory(ClientFactory):
    protocol = TunnelProtocol
    
    def __init__(self, reactor, protocolClass, args, kwargs, deferred, host, port, headers=(), contextFactory=None, timeout=30):
        self.reactor = reactor
        self.protocolClass = protocolClass
        self.args = args
        self.kwargs = kwargs
        self.deferred = deferred
        self.host = host
        self.port = port
        self.headers = headers
        self.contextFactory = contextFactory
        self.timeout = timeout
    
    def sendResult(self, result):
        self.reactor.callLater(0, self.deferred.callback, result)
        del self.deferred
    
    def sendError(self, failure):
        self.reactor.callLater(0, self.deferred.errback, failure)
        del self.deferred
    
    def clientConnectionFailed(self, connector, failure):
        self.sendError(failure)
    
    def gotTunnel(self, tunnel):
        try:
            instance = self.protocolClass(*self.args, **self.kwargs)
            tunnel.startTunneling(instance)
            self.sendResult(instance)
        except:
            self.sendError(Failure())
    
    def gotError(self, failure):
        self.sendError(failure)

class TunnelCreator(object):
    def __init__(self, reactor, proxy, protocolClass, *args, **kwargs):
        self.reactor = reactor
        self.proxyhost, self.proxyport = _parseProxy(proxy)
        self.proxyheaders = kwargs.pop('proxyheaders', ())
        self.protocolClass = protocolClass
        self.args = args
        self.kwargs = kwargs
    
    def connectTCP(self, host, port, timeout=30, bindAddress=None):
        d = Deferred()
        try:
            f = TunnelFactory(self.reactor, self.protocolClass, self.args, self.kwargs, d, host, port, self.proxyheaders, timeout=timeout)
            self.reactor.connectTCP(self.proxyhost, self.proxyport, f, timeout=timeout, bindAddress=bindAddress)
        except:
            d.errback(Failure())
        return d
    
    def connectSSL(self, host, port, contextFactory, timeout=30, bindAddress=None):
        d = Deferred()
        try:
            f = TunnelFactory(self.reactor, self.protocolClass, self.args, self.kwargs, d, host, port, self.proxyheaders, contextFactory, timeout=timeout)
            self.reactor.connectTCP(self.proxyhost, self.proxyport, f, timeout=timeout, bindAddress=bindAddress)
        except:
            d.errback(Failure())
        return d
