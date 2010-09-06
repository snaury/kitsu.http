__all__ = ['Response', 'ResponseParser']

from kitsu.http.errors import *
from kitsu.http.headers import Headers
from kitsu.http.parsers import LineParser

class Response(object):
    __slots__ = ('version', 'code', 'phrase', 'headers', 'body', '__parserState')
    
    def __init__(self, version=(1,1), code=200, phrase='OK', headers=(), body=None):
        self.version = version
        self.code = code
        self.phrase = phrase
        self.headers = Headers(headers)
        self.body = body
        self.__parserState = 'STATUS'
    
    def toLines(self, lines=None):
        if lines is None:
            lines = []
        lines.append("HTTP/%d.%d %d %s\r\n" % (self.version[0], self.version[1], self.code, self.phrase))
        self.headers.toLines(lines)
        lines.append("\r\n")
        return lines
    
    def toString(self):
        return ''.join(self.toLines())
    
    def __str__(self):
        return self.toString()
    
    def __parseStatus(self, line):
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
        if self.__parserState == 'STATUS':
            if not line:
                # http://www.w3.org/Protocols/rfc2616/rfc2616-sec4.html
                # Just ignore all empty lines for maximum compatibility
                return True
            self.__parseStatus(line)
            self.__parserState = 'HEADERS'
            return True
        elif self.__parserState == 'HEADERS':
            if not self.headers.parseLine(line):
                self.__parserState = 'DONE'
                return False
            return True
        return False

class ResponseParser(LineParser):
    """Response parser"""
    
    def __init__(self):
        self.response = Response()
    
    def parseLine(self, line):
        if not self.response.parseLine(line):
            self.done = True
            return [self.response]
        return []
