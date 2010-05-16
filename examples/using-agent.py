#!/usr/bin/env python
# Copyright (c) 2010 Alexey Borzenkov.
# See LICENSE for details.

import sys
sys.path.append('..')
from datetime import datetime
from twisted.internet import reactor
from kitsu_http import *

def main():
    agent = HTTPAgent(reactor)
    agent.timeout = 5
    agent.closeOnSuccess = False
    urls = ['https://mail.google.com/mail', 'http://git.kitsu.ru', 'http://git.kitsu.ru/mine/kitsu-http.git']
    
    def gotResponse(response):
        stamp = str(datetime.now().ctime())
        print "[%s] Got response from %s" % (stamp, response.url)
        print "[%s] HTTP/%d.%d %d %s" % (stamp, response.version[0], response.version[1], response.code, response.phrase)
        for name, values in response.headers.iteritems():
            if not isinstance(values, list):
                values = [values]
            for value in values:
                print "[%s] %s: %r" % (stamp, name, value)
        if response.body:
            print "[%s] (%d bytes)" % (stamp, len(response.body or ''))
        makeNextRequest()
    
    def gotError(failure):
        if reactor.running:
            reactor.stop()
        print "[%s] Got error:" % (datetime.today(),)
        failure.printTraceback()
    
    def makeNextRequest():
        if not urls:
            agent.close()
            reactor.stop()
            return
        url = urls.pop(0)
        agent.makeRequest(
            url,
            headers={ 'User-Agent' : 'Kitsu http client', 'X-Custom-Header' : 'My value' },
            proxy=('127.0.0.1', 8001),
            proxyheaders={ 'Proxy-Authorization' : 'my-secret-goes-here' },
            proxytype='https',
        ).addCallbacks(gotResponse, gotError)
    
    makeNextRequest()

reactor.callLater(0, main)
print "Reactor running..."
reactor.run()
print "Reactor stopped"
