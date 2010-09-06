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
    def __init__(self, sock, bodylimit=None, packetsize=4096):
        self.sock = sock
        self.data = ''
        self.bodylimit = bodylimit
        self.packetsize = packetsize
    
    def __del__(self):
        self.close()
    
    def close(self):
        self.sock.close()
    
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
        self.__send(request.toString())
        self.__sendBody(request.body)
        parser = ResponseParser()
        if not self.data:
            self.data = self.__recv()
        while True:
            if not self.data:
                raise HTTPError("not enough data")
            response = parser.parse(self.data)
            if response:
                self.data = parser.clear()
                assert parser.done
                assert len(response) == 1
                response = response[0]
                break
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
                    raise HTTPError("too much data")
        def process_chunks(chunks):
            for chunk in chunks:
                process_chunk(chunk)
        if not self.data:
            self.data = self.__recv()
        while True:
            if not self.data:
                break
            process_chunks(decoder.parse(self.data))
            if decoder.done:
                break
            self.data = self.__recv()
        process_chunks(decoder.finish())
        self.data = decoder.clear()
        response.body = response.body.getvalue()
        return response

class Agent(object):
    pass
