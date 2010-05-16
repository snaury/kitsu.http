#!/usr/bin/env python
# Copyright (c) 2010 Alexey Borzenkov.
# See LICENSE for details.

import sys
sys.path.append('..')
from twisted.internet.protocol import Protocol
from twisted.internet import reactor
from twisted.internet import ssl
from kitsu_http import *

class MyProtocol(Protocol):
    def connectionMade(self):
        print "Tunnel connected!"
        self.transport.write('GET / HTTP/1.0\r\nHost: www.google.com\r\n\r\n')
    
    def connectionLost(self, reason):
        print "Tunnel disconnected."
    
    def dataReceived(self, data):
        print "Tunnel received: %r" % (data,)

def main():
    c = TunnelCreator(reactor, ('127.0.0.1', 8001), MyProtocol, proxyheaders = {'Proxy-Authorization': 'my-secret-here'})
    c.connectTCP('www.google.com', 80)
    c.connectSSL('www.google.com', 443, ssl.ClientContextFactory())

reactor.callLater(0, main)
reactor.run()
