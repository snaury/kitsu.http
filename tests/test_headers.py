# -*- coding: utf-8 -*-
import unittest
from kitsu.http.headers import *

HEADERS_NORMAL = """\
cookies: cookie1
cookies: cookie2
content-type: application/octet-stream
www-authenticate: Basic
""".replace("\n", "\r\n")

HEADERS_CANONICAL = """\
Cookies: cookie1
Cookies: cookie2
Content-Type: application/octet-stream
WWW-Authenticate: Basic
""".replace("\n", "\r\n")

HEADERS_UNICODE_CANONICAL = """\
Cookies: cookie1
Cookies: cookie2
Content-Type: application/octet-stream
WWW-Authenticate: Basic
Проверка: test
""".replace("\n", "\r\n")

HEADERS_REPLACE = """\
content-type: application/octet-stream
www-authenticate: Basic
cookies: cookie3
""".replace("\n", "\r\n")

HEADERS_ORDER_AND_CASE = """\
cookies: cookie1
cookies: cookie2
content-type: application/octet-stream
www-authenticate: Basic
Cookies: cookie3
""".replace("\n", "\r\n")

HEADERS_MIDDLE_REMOVED = """\
cookies: cookie1
cookies: cookie2
www-authenticate: Basic
""".replace("\n", "\r\n")

HEADERS_NUMBER = """\
cookies: cookie1
cookies: cookie2
content-type: application/octet-stream
www-authenticate: Basic
content-length: 123
""".replace("\n", "\r\n")

HEADERS_PARSING = """\
Header1: value
Header2: value
 with another line
Header3: more values
Header1: another value
""".replace("\n", "\r\n")

class HeadersTests(unittest.TestCase):
    def setUp(self):
        self.headers = Headers()
        self.headers['cookies'] = ['cookie1', 'cookie2']
        self.headers['content-type'] = 'application/octet-stream'
        self.headers['www-authenticate'] = 'Basic'
    
    def test_normal(self):
        self.assertEqual(self.headers.toString(), HEADERS_NORMAL)
    
    def test_canonical(self):
        self.assertEqual(self.headers.toString(canonical=True), HEADERS_CANONICAL)
    
    def test_unicode_canonical(self):
        self.headers[u'проВерка'] = 'test'
        self.assertEqual(self.headers.toString(canonical=True), HEADERS_UNICODE_CANONICAL)
    
    def test_replace(self):
        self.headers['cookies'] = ['cookie3']
        self.assertEqual(self.headers.toString(), HEADERS_REPLACE)
    
    def test_order_and_case(self):
        self.headers.add('Cookies', 'cookie3')
        self.assertEqual(self.headers.toString(), HEADERS_ORDER_AND_CASE)
    
    def test_order_and_case_copy(self):
        self.headers.add('Cookies', 'cookie3')
        self.assertEqual(Headers(self.headers).toString(), HEADERS_ORDER_AND_CASE)
    
    def test_middle_removed(self):
        del self.headers['CONTENT-TYPE']
        self.assertEqual(self.headers.toString(), HEADERS_MIDDLE_REMOVED)
    
    def test_number1(self):
        self.headers['content-length'] = 123
        self.assertEqual(self.headers.toString(), HEADERS_NUMBER)
    
    def test_number2(self):
        self.headers['content-length'] = [123]
        self.assertEqual(self.headers.toString(), HEADERS_NUMBER)
    
    def test_invalid_key(self):
        self.assertRaises(KeyError, self.headers.__setitem__, 1, 'test')
    
    def test_parsing(self):
        headers = Headers()
        for line in HEADERS_PARSING.split("\r\n"):
            res = headers.parseLine(line)
        self.assertFalse(res)
        self.assertEqual(headers.toString(), HEADERS_PARSING)

if False:
    def whiny(self, *args, **kwargs):
        print "whiny: %r" % (self,)

    h = Headers()
    h['content-Type'] = 'application/octet-stream'
    h['cookies'] = ['cookie1', 'cookie2']
    h[u'проВерка'] = '0123'
    h['Content-Length'] = '1234'
    h.add('Cookies', 'cookie3')
    print h.toString()
    h[u'проверка'] = u'проверка'
    h['cookies'] = 'hello world'
    print h.toString()
    del h['Cookies']
    print h.toString(canonical=True)

    h = Headers()
    h.parseLine('Header1: value')
    h.parseLine('Header2: value')
    h.parseLine(' and value')
    h.parseLine('Header3: value')
    h.parseLine('Header1: another value')
    h.parseLine('')
    print h
    print Headers(h)
