__all__ = [
    'Response',
    'ResponseParser',
]

from kitsu.http.errors import *
from kitsu.http.headers import Headers
from kitsu.http.parsers import LineParser

class Response(object):
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
            raise HTTPDataError("response must be in 'HTTP/n.n status message' format: %r" % (line,))
        version = parts[0]
        code = parts[1]
        phrase = len(parts) >= 3 and parts[2] or ""
        if not version.startswith('HTTP/'):
            raise HTTPDataError("protocol must be HTTP: %r" % (line,))
        version = version[5:].split('.')
        if len(version) != 2:
            raise HTTPDataError("invalid version: %r" % (line,))
        try:
            version = (int(version[0]), int(version[1]))
        except ValueError:
            raise HTTPDataError("invalid version: %r" % (line,))
        try:
            code = int(code)
        except ValueError:
            raise HTTPDataError("status code must be a number: %r" % (line,))
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
