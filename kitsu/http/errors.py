__all__ = ['HTTPError', 'HTTPTimeout']

class HTTPError(Exception):
    pass

class HTTPTimeout(HTTPError):
    pass
