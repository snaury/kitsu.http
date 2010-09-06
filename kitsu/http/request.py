__all__ = ['Request', 'RequestParser']

from kitsu.http.errors import *
from kitsu.http.headers import Headers
from kitsu.http.parsers import LineParser

class Request(object):
    __slots__ = ('method', 'target', 'version', 'headers', 'body', '__parserState')
    
    def __init__(self, method="GET", target="/", version=(1,1), headers=(), body=None):
        self.method = method
        self.target = target
        self.version = version
        self.headers = Headers(headers)
        self.body = body
        self.__parserState = 'COMMAND'
    
    def toLines(self, lines=None):
        if lines is None:
            lines = []
        lines.append("%s %s HTTP/%d.%d\r\n" % (self.method, self.target, self.version[0], self.version[1]))
        self.headers.toLines(lines)
        lines.append("\r\n")
        return lines
    
    def toString(self):
        return ''.join(self.toLines())
    
    def __str__(self):
        return self.toString()
    
    def __parseCommand(self, line):
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
        if self.__parserState == 'COMMAND':
            if not line:
                # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html
                # Just ignore all empty lines for maximum compatibility
                return True
            self.__parseCommand(line)
            self.__parserState = 'HEADERS'
            return True
        elif self.__parserState == 'HEADERS':
            if not self.headers.parseLine(line):
                self.__parserState = 'DONE'
                return False
            return True
        return False

class RequestParser(LineParser):
    """Request parser"""
    
    def __init__(self):
        self.request = Request()
    
    def parseLine(self, line):
        if not self.request.parseLine(line):
            self.done = True
            return (self.request,)
        return ()
