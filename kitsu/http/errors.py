__all__ = ['HTTPError', 'HTTPDataError', 'HTTPLimitError', 'HTTPTimeoutError']

class HTTPError(Exception):
    def __str__(self):
        cls = type(self)
        doc = getattr(cls, '__doc__')
        text = Exception.__str__(self)
        if doc and text:
            return "%s: %s" % (doc, text)
        return doc or text

class HTTPDataError(HTTPError):
    """Data error"""

class HTTPLimitError(HTTPError):
    """Data limit exceeded"""

class HTTPTimeoutError(HTTPError):
    """Timeout limit exceeded"""
