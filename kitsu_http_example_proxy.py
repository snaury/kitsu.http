#!/usr/bin/env python
# Copyright (c) 2010 Alexey Borzenkov.
# See LICENSE for details.

from twisted.internet.protocol import Protocol, ServerFactory, ClientCreator
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor
from twisted.internet import ssl
from kitsu_http import *

class TunnelProtocol(Protocol):
    target = None
    
    def dataReceived(self, data):
        assert self.target
        self.target.write(data)
    
    def connectionLost(self, failure):
        assert self.target
        self.target.loseConnection()

class ProxyProtocol(LineReceiver):
    target = None
    request = None
    
    def lineReceived(self, line):
        print "%r: %r" % (self.transport.client, line)
        if self.request is None:
            self.request = Request()
        if not self.request.parseLine(line):
            # We've got a request!
            good = False
            if self.request.method == 'CONNECT':
                netloc = self.request.target
                if ':' in netloc:
                    host, port = netloc.split(':', 1)
                    try:
                        port = int(port)
                        good = True
                    except:
                        pass
            if not good:
                self.transport.write("HTTP/1.1 500 Server Error\r\nConnection: close\r\n\r\nExample proxy was unable to process your request")
                self.transport.loseConnection()
                return
            c = ClientCreator(reactor, TunnelProtocol)
            c.connectTCP(host, port).addCallback(self.gotConnection).addErrback(self.gotError)
            self.setRawMode()
    
    def rawDataReceived(self, data):
        assert self.target
        self.target.write(data)
    
    def gotConnection(self, protocol):
        self.target = protocol.transport
        protocol.target = self.transport
        self.transport.write("HTTP/1.1 200 Connected\r\n\r\n")
    
    def gotError(self, failure):
        if self.target:
            self.target.loseConnection()
        self.transport.write("HTTP/1.1 500 Server Error\r\nConnection: close\r\n\r\nExample proxy error: %s" % (failure,))
        self.transport.loseConnection()
        return failure
    
    def connectionMade(self):
        print "Client connected: %r" % (self.transport.client,)
        self.factory.numclients += 1
    
    def connectionLost(self, failure):
        print "Client disconnected: %r" % (self.transport.client,)
        self.factory.numclients -= 1

class ProxyFactory(ServerFactory):
    protocol = ProxyProtocol
    numclients = 0

reactor.listenTCP(8001, ProxyFactory(), interface='127.0.0.1')

print "Reactor running..."
reactor.run()
print "Reactor stopped."
