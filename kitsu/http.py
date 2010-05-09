from urlparse import urlsplit, urljoin
from zope.interface import implements
from twisted.python.failure import Failure
from twisted.internet.protocol import Protocol, ClientCreator
from twisted.protocols.basic import LineReceiver
from twisted.internet.defer import Deferred, maybeDeferred

_canonicalHeaderParts = { 'www' : 'WWW' }
def _canonicalHeaderName(name):
    def canonical(part):
        return _canonicalHeaderParts.get(part) or part.capitalize()
    return '-'.join(canonical(part.lower()) for part in name.split('-'))

class HeadersError(RuntimeError):
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
    
    def flushPartialHeader(self):
        if self._partialHeader:
            header = ''.join(self._partialHeader)
            del self._partialHeader
            parts = header.split(':', 1)
            if len(parts) != 2:
                raise HeadersError("header must be in 'name: value' format")
            name = parts[0].rstrip()
            value = parts[1].strip()
            if not name:
                raise HeadersError("header must be in 'name: value' format")
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

class RequestError(RuntimeError):
    pass

class Request(object):
    """
    HTTP Request
    """
    
    _parserState = 'COMMAND'
    
    def __init__(self, method="GET", path="/", version=(1,1), headers=(), body=None):
        self.method = method
        self.path = path
        self.version = version
        self.headers = Headers(headers)
        self.body = body
    
    def _writeHeaders(self, transport):
        lines = ["%s %s HTTP/%d.%d\r\n" % (self.method, self.path, self.version[0], self.version[1])]
        for name, values in self.headers.iteritems():
            name = _canonicalHeaderName(name)
            if not isinstance(values, list):
                values = [values]
            for value in values:
                lines.append("%s: %s\r\n" % (name, value))
        lines.append("\r\n")
        transport.writeSequence(lines)
    
    def writeTo(self, transport):
        self._writeHeaders(transport)
        if self.body:
            transport.write(self.body)
    
    def _parseCommand(self, line):
        parts = line.split(None, 2)
        if len(parts) != 3:
            raise RequestError("request must be in 'METHOD path HTTP/n.n' format")
        method, path, version = parts
        if not version.startswith('HTTP/'):
            raise RequestError("protocol must be HTTP")
        version = version[5:].split('.')
        if len(version) != 2:
            raise RequestError("invalid version")
        try:
            version = (int(version[0]), int(version[1]))
        except ValueError:
            raise RuntimeError("invalid version")
        self.method = method
        self.path = path
        self.version = version
    
    def parseLine(self, line):
        if self._parserState == 'COMMAND':
            self._parseCommand(line)
            self._parserState = 'HEADERS'
        elif self._parserState == 'HEADERS':
            if not self.headers.parseLine(line):
                self._parserState = 'DONE'
        return line and True or False

class ResponseError(RuntimeError):
    pass

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
        for name, values in self.headers.iteritems():
            name = _canonicalHeaderName(name)
            if not isinstance(values, list):
                values = [values]
            for value in values:
                lines.append("%s: %s\r\n" % (name, value))
        lines.append("\r\n")
        transport.writeSequence(lines)
    
    def writeTo(self, transport):
        self._writeHeaders(transport)
        if self.body:
            transport.write(self.body)
    
    def _parseStatus(self, line):
        parts = line.split(None, 2)
        if len(parts) not in (2, 3):
            raise ResponseError("response must be in 'HTTP/n.n status message' format")
        version = parts[0]
        code = parts[1]
        phrase = len(parts) >= 3 and parts[2] or ""
        if not version.startswith('HTTP/'):
            raise ResponseError("protocol must be HTTP")
        version = version[5:].split('.')
        if len(version) != 2:
            raise ResponseError("invalid version")
        try:
            version = (int(version[0]), int(version[1]))
        except ValueError:
            raise ResponseError("invalid version")
        try:
            code = int(code)
        except ValueError:
            raise ResponseError("status code must be a number")
        self.version = version
        self.code = code
        self.phrase = phrase
    
    def parseLine(self, line):
        if self._parserState == 'STATUS':
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

class HTTPRequestParser(LineParser):
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

class HTTPResponseParser(LineParser):
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

class HTTPChunkedDecoder(LineParser):
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

class HTTPIdentityDecoder(Parser):
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

class HTTPClientError(RuntimeError):
    pass

class HTTPClient(Protocol):
    """
    HTTP Client
    """
    
    def __init__(self):
        self._reset()
    
    def _reset(self):
        self.__buffer = None
        self.state = 'IDLE'
        self.result = None
        self.parser = None
        self.request = None
        self.response = None
        self.decoders = None
        self.readingChunked = False
        self.readingUntilClosed = False
    
    def _flushBuffer(self):
        if self.parser and self.__buffer:
            data, self.__buffer = self.__buffer, ''
            self.dataReceived(data)
    
    def _succeed(self, response):
        result = self.result
        self._reset()
        if result:
            result.callback(response)
    
    def _fail(self, failure):
        result = self.result
        self._reset()
        if result:
            result.errback(failure)
    
    def makeRequest(self, request):
        if self.state != 'IDLE':
            return fail(RuntimeError("HTTP Client must be idle to make new requests"))
        
        self.state = 'TRANSMITTING'
        self.result = Deferred()
        self.parser = HTTPResponseParser()
        self.request = request
        self.request.writeTo(self.transport)
        self._flushBuffer()
        return self.result
    
    def connectionLost(self, failure):
        if self.result:
            if self.response and self.readingUntilClosed:
                # We were reading data up to the end
                self._succeed(self.response)
            else:
                # We were either parsing or reading data
                self._fail(failure)
    
    def dataReceived(self, data):
        try:
            if data and self.parser:
                response = self.parser.parse(data)
                if response:
                    assert len(response) == 1
                    response = response[0]
                    assert self.parser.done
                    data = self.parser.clear()
                    self.gotResponse(response)
                else:
                    data = ''
            if data and self.decoders:
                current = [data]
                for parser in self.decoders:
                    output = []
                    for chunk in current:
                        output.extend(parser.parse(chunk))
                    if output and isinstance(parser, HTTPChunkedDecoder):
                        # We might have trailer headers in the output
                        if isinstance(output[-1], Headers):
                            headers = output.pop()
                            for name, values in headers.iteritems():
                                if not isinstance(values,list):
                                    values = [values]
                                for value in values:
                                    self.headers.add(name, value)
                    current = output
                if self.decoders[0].done:
                    data = self.decoders[0].clear()
                    finished = True
                else:
                    data = ''
                    finished = False
                self.gotBodyBytes(''.join(current), finished)
            if data:
                self.__buffer += data
        except:
            self._fail(Failure())
    
    def gotResponse(self, response):
        self.parser = None
        self.response = response
        
        # process Content-Length
        contentLength = response.headers.get('Content-Length')
        if isinstance(contentLength, list):
            contentLength = contentLength[0]
        if contentLength:
            contentLength = int(contentLength)
        else:
            contentLength = None
        if self.request.method == 'HEAD':
            contentLength = 0
        elif contentLength is None and response.code in (204, 304):
            contentLength = 0
        
        # process Transfer-Encoding
        encodings = response.headers.get('Transfer-Encoding')
        if encodings is None:
            encodings = ['identity']
        if not isinstance(encodings, list):
            encodings = [encodings]
        encodings = ', '.join(encodings)
        encodings = [encoding.strip() for encoding in encodings.split(',')]
        decoders = []
        for encoding in encodings:
            encoding = encoding.split(';', 1)[0] # strip parameters
            encoding = encoding.strip().lower()
            if encoding == 'chunked':
                decoders.append(HTTPChunkedDecoder())
                self.readingChunked = True
            elif encoding == 'identity':
                decoders.append(HTTPIdentityDecoder(contentLength))
                self.readingUntilClosed = contentLength is None
            else:
                raise HTTPClientError("Don't know how to decode Transfer-Encoding %r" % (encoding,))
        decoders.reverse()
        self.decoders = decoders
    
    def gotBodyBytes(self, body, finished=False):
        if self.response.body is None:
            self.response.body = ''
        self.response.body += body
        if finished:
            self._succeed(self.response)

class HTTPAgent(object):
    def __init__(self):
        self.reactor = None
        self.proxy = None
        self.result = None
        self.request = None
        self.client = None
        self.current_host = None
        self.current_port = None
        self.current_url = None
    
    def _succeeded(self, response):
        if self.result:
            if self.client:
                self.client.transport.loseConnection()
                self.client = None
            self.result.callback(response)
            self.result = None
        else:
            raise RuntimeError, "_succeded called without result"
    
    def _failed(self, failure):
        if self.result:
            if self.client:
                self.client.transport.loseConnection()
                self.client = None
            self.result.errback(failure)
            self.result = None
        else:
            raise RuntimeError, "_failed called without result"
    
    def parseArguments(self, url, method='GET', version=(1,1), headers=(), body=None, proxy=None):
        scheme, netloc, path, query, fragment = urlsplit(url)
        if ':' in netloc:
            host, port = netloc.split(':')
            port = int(port)
        else:
            host = netloc
            if scheme == 'https':
                port = 443
            else:
                port = 80
        if proxy is None:
            if not path.startswith('/'):
                path = '/' + path
            if query:
                path = path + '?' + query
        else:
            path = url
        headers = Headers(headers)
        headers['Host'] = netloc
        if body:
            headers['Content-Length'] = "%d" % (len(body),)
        if proxy is not None:
            host, port = proxy.split(':', 1)
            port = int(port)
        return host, port, Request(method=method, path=path, version=version, headers=headers, body=body)
    
    def makeRequest(self, reactor, url, method='GET', version=(1,1), headers=(), body=None, proxy=None):
        self.reactor = reactor
        host, port, request = self.parseArguments(url, method, version, headers, body, proxy)
        self.proxy = proxy
        self.result = Deferred()
        self.request = request
        self.current_url  = url
        self.connectTo(host, port)
        return self.result
    
    def connectTo(self, host, port):
        if self.client:
            if (self.current_host, self.current_port) == (host, port):
                # no need to reconnect, reuse current client
                r = self.client.makeRequest(self.request)
                r.addCallback(self.gotResponse).addErrback(self.gotError)
                return
            self.client.transport.loseConnection()
            self.client = None
        self.current_host = host
        self.current_port = port
        c = ClientCreator(self.reactor, HTTPClient)
        c.connectTCP(host, port).addCallback(self.gotProtocol).addErrback(self.gotError)
    
    def gotProtocol(self, protocol):
        self.client = protocol
        peer = self.client.transport.getPeer()
        r = self.client.makeRequest(self.request)
        r.addCallback(self.gotResponse).addErrback(self.gotError)
    
    def gotResponse(self, response):
        if response.code in (301, 302, 303, 307):
            url = response.headers.get('Location')
            if url and isinstance(url, list):
                url = url[0]
            if url:
                url = urljoin(self.current_url, url)
                host, port, request = self.parseArguments(url, self.request.method, self.request.version, self.request.headers, self.request.body, self.proxy)
                self.request = request
                self.current_url = url
                self.connectTo(host, port)
                return
        self._succeeded(response)
    
    def gotError(self, failure):
        self._failed(failure)
