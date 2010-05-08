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

class Headers(dict):
    _partialHeader = None
    
    def flushPartialHeader(self):
        if self._partialHeader:
            header = ''.join(self._partialHeader)
            del self._partialHeader
            parts = header.split(':', 1)
            if len(parts) != 2:
                raise HeadersError("header must be in 'name: value' format")
            name = parts[0].rstrip().lower()
            value = parts[1].strip()
            values = self.setdefault(name, [])
            if isinstance(values,basestring):
                values = [values]
                self[name] = values
            values.append(value)
    
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
        for name,values in self.headers.iteritems():
            name = _canonicalHeaderName(name)
            if isinstance(values,basestring):
                values = (values,)
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
            raise RequestError("request should be in 'METHOD path HTTP/n.n' format")
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
        for name,values in self.headers.iteritems():
            name = _canonicalHeaderName(name)
            if isinstance(values,basestring):
                values = (values,)
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
            raise ResponseError("response should be in 'HTTP/n.n status message' format")
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

class HTTPClientParser(LineReceiver):
    """
    HTTP Client Parser
    """
    
    state = 'RESPONSE'
    
    def __init__(self, callback=None, errback=None, databack=None):
        self.response = Response()
        self.callback = callback
        self.errback = errback
        self.databack = databack
    
    def lineReceived(self, line):
        try:
            if self.state == 'RESPONSE':
                if not self.response.parseLine(line):
                    self.state = 'DATA'
                    self.setRawMode()
                    if self.callback:
                        self.callback(self, self.response)
        except:
            self.state = 'ERROR'
            self.errback(self, Failure())
    
    def rawDataReceived(self, data):
        try:
            if self.databack:
                self.databack(self, data)
        except:
            self.state = 'ERROR'
            self.errback(self, Failure())

class HTTPServerParser(LineReceiver):
    """
    HTTP Server Parser
    """
    
    state = 'REQUEST'
    
    def __init__(self, callback=None, errback=None, databack=None):
        self.request = Request()
        self.callback = callback
        self.errback = errback
        self.databack = databack
    
    def lineReceived(self, line):
        try:
            if self.state == 'REQUEST':
                if not self.request.parseLine(line):
                    self.state = 'DATA'
                    self.setRawMode()
                    if self.callback:
                        self.callback(self, self.request)
        except:
            self.state = 'ERROR'
            self.errback(self, Failure())
    
    def rawDataReceived(self, data):
        try:
            if self.databack:
                self.databack(self, data)
        except:
            self.state = 'ERROR'
            self.errback(self, Failure())

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
        self.contentLength = None
    
    def _flushBuffer(self):
        if self.parser and self.__buffer:
            data = self.__buffer
            self.__buffer = ''
            self.parser.dataReceived(data)
    
    def _succeed(self, response):
        result = self.result
        if result:
            self._reset()
            result.callback(response)
    
    def _fail(self, failure):
        result = self.result
        if result:
            self._reset()
            result.errback(failure)
    
    def makeRequest(self, request):
        if self.state != 'IDLE':
            return fail(RuntimeError("HTTP Client must be idle to make new requests"))
        
        self.state = 'TRANSMITTING'
        self.result = Deferred()
        self.parser = HTTPClientParser(self.parser_callback, self.parser_errback, self.parser_databack)
        self.parser.makeConnection(self.transport)
        self.request = request
        self.request.writeTo(self.transport)
        self._flushBuffer()
        return self.result
    
    def connectionLost(self, failure):
        if self.response and self.contentLength is None:
            # We were reading data up to the end
            self._succeed(self.response)
        else:
            # We were either parsing or reading data
            self._fail(failure)
    
    def dataReceived(self, data):
        if self.parser:
            self._flushBuffer()
            self.parser.dataReceived(data)
            return
        if self.response:
            if self.contentLength is None:
                body, data = data, ''
            elif self.contentLength:
                body, data = data[:self.contentLength], data[self.contentLength:]
                self.contentLength -= len(body)
            else:
                body = None
            if body:
                if self.response.body is None:
                    self.response.body = ''
                self.response.body += body
                if self.contentLength == 0:
                    self._succeed(self.response)
        if data:
            self.__buffer += data
    
    def parser_callback(self, parser, response):
        self.parser = None
        self.response = response
        contentLength = response.headers.get('content-length')
        if contentLength:
            contentLength = contentLength[0] or None
        if contentLength:
            contentLength = int(contentLength)
        if response.code in (204, 304) or self.request.method == 'HEAD':
            contentLength = 0
        self.contentLength = contentLength
    
    def parser_errback(self, parser, failure):
        self._fail(failure)
    
    def parser_databack(self, parser, data):
        assert self.parser is not parser # shouldn't happen, will recurse otherwise
        self.dataReceived(data)

def make_http_request(reactor, host, port, request):
    d = Deferred()
    def gotProtocol(http):
        def httpClose(*args):
            http.transport.loseConnection()
        r = http.makeRequest(request)
        r.chainDeferred(d).addBoth(httpClose)
    c = ClientCreator(reactor, HTTPClient)
    c.connectTCP(host, port).addCallbacks(gotProtocol, d.errback)
    return d
