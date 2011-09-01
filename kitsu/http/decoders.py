__all__ = [
    'IdentityDecoder',
    'ChunkedDecoder',
    'DeflateDecoder',
    'CompoundDecoder',
]

from kitsu.http.errors import *
from kitsu.http.headers import *
from kitsu.http.parsers import *

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
            return (body,)
        return ()
    
    def finish(self):
        if not self.done:
            self.done = True
            if self.length:
                raise HTTPDataError("not enough data for content body")
        return ()

class ChunkedDecoder(LineParser):
    def __init__(self):
        self.length = None
        self.extensions = None
        self.headers = None
    
    def parseLine(self, line):
        if self.headers is not None:
            # Reading trailer headers
            if not self.headers.parseLine(line):
                self.done = True
                return (self.headers,)
        elif self.length == 0:
            # Just finished reading chunk
            if line:
                raise HTTPDataError("chunk data must end with '\\r\\n'")
            self.length = None
        else:
            # Reading chunk header
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
        return ()
    
    def parseData(self, data):
        body, data = data[:self.length], data[self.length:]
        self.length -= len(body)
        if self.length == 0:
            self.setLineMode(data)
        return (body,)
    
    def finish(self):
        if not self.done:
            self.done = True
            raise HTTPDataError("not enough data for chunked body")
        return ()

class DeflateDecoder(Parser):
    def __init__(self):
        from zlib import decompressobj
        self.obj = decompressobj()
    
    def parseRaw(self, data):
        data = self.obj.decompress(data)
        if data:
            return (data,)
        return ()
    
    def finish(self):
        if not self.done:
            self.done = True
            data = self.obj.flush()
            self.prepend(self.obj.unused_data)
            self.obj = None
            if data:
                return (data,)
        return ()

class CompoundDecoder(Parser):
    def __init__(self, *args):
        self.decoders = list(args)
    
    def _process(self, chunks, finish=False):
        first = self.decoders[0]
        for decoder in self.decoders:
            output = []
            for chunk in chunks:
                if isinstance(chunk, basestring):
                    output.extend(decoder.parse(chunk))
                else:
                    output.append(chunk)
            if finish:
                output.extend(decoder.finish())
            if decoder is first:
                self.done = self.done or decoder.done
            chunks = output
        return chunks
    
    def clear(self):
        return self.decoders[0].clear()
    
    def parseRaw(self, data):
        result = self._process((data,))
        if self.done:
            # Outer decoder finished
            # Chain finish calls
            result = list(result)
            result.extend(self._process((), True))
        return result
    
    def finish(self):
        if not self.done:
            self.done = True
            return self._process((), True)
        return ()
    
    requestMethodsWithoutBody = frozenset(('HEAD', 'CONNECT'))
    responseCodesWithoutBody = frozenset((204, 304))
    
    @classmethod
    def from_response(cls, method, response):
        # process Content-Length
        contentLength = response.headers.getlist('Content-Length')
        if contentLength:
            contentLength = contentLength[-1]
            if contentLength:
                try:
                    contentLength = int(contentLength)
                except ValueError:
                    raise HTTPDataError("invalid Content-Length header")
            else:
                contentLength = None
        else:
            contentLength = None
        if method in cls.requestMethodsWithoutBody:
            contentLength = 0
        if contentLength is None and response.code in cls.responseCodesWithoutBody:
            contentLength = 0
        if contentLength == 0:
            return None
        
        # process Transfer-Encoding
        encodings = response.headers.get('Transfer-Encoding')
        if encodings is None:
            encodings = 'identity'
        encodings = [encoding.strip() for encoding in encodings.split(',')]
        encodings.reverse()
        decoders = []
        baseDecoderFound = False
        for encoding in encodings:
            encoding = encoding.split(';', 1)[0] # strip parameters
            encoding = encoding.strip().lower()
            if encoding == 'chunked':
                if decoders:
                    raise HTTPDataError("'chunked' must be the last Transfer-Encoding in chain")
                decoders.append(ChunkedDecoder())
                baseDecoderFound = True
            elif encoding == 'identity':
                if decoders:
                    raise HTTPDataError("'identity' must be the last Transfer-Encoding in chain")
                decoders.append(IdentityDecoder(contentLength))
                baseDecoderFound = True
            elif encoding == 'deflate':
                decoders.append(DeflateDecoder())
            else:
                # TODO: implement gzip, bzip2?
                raise HTTPDataError("no decoder for Transfer-Encoding %r" % (encoding,))
        if not baseDecoderFound:
            # Don't fail if identity not specified
            decoders.insert(0, IdentityDecoder(contentLength))
        return cls(*decoders)
