from kitsu.http.errors import *

__all__ = ['Headers']

_canonicalHeaderParts = { 'www' : 'WWW' }
def _canonicalHeaderName(name):
    def canonical(part):
        return _canonicalHeaderParts.get(part) or part.capitalize()
    return '-'.join(canonical(part.lower()) for part in name.split('-'))

nil = object()

class Header(object):
    __slots__ = ('name', 'value', 'prev', 'next', 'prev_value', 'next_value')
    
    def __init__(self, name, value, prev=None, next=None, prev_value=None, next_value=None):
        self.name = name
        self.value = value
        self.prev = prev
        self.next = next
        self.prev_value = prev_value
        self.next_value = next_value
    
    def unlink(self):
        if self.prev is not None:
            self.prev.next = self.next
        if self.next is not None:
            self.next.prev = self.prev
        if self.prev_value is not None:
            self.prev_value.next_value = self.next_value
        if self.next_value is not None:
            self.next_value.prev_value = self.prev_value
        self.prev = None
        self.next = None
        self.prev_value = None
        self.next_value = None
    
    def __repr__(self):
        def objref(obj):
            if isinstance(obj, Header):
                return "0x%x" % id(obj)
            return repr(obj)
        return "<Header(name=%r, value=%r, prev=%s, next=%s, prev_value=%s, next_value=%s) at 0x%x>" % (self.name, self.value, objref(self.prev), objref(self.next), objref(self.prev_value), objref(self.next_value), id(self))

class Headers(object):
    __slots__ = ('__head', '__tail', '__values', 'encoding', '__partialHeader')
    
    def __init__(self, data=(), encoding='utf-8'):
        self.__head = None
        self.__tail = None
        self.__values = {}
        self.encoding = encoding
        self.__partialHeader = None
        if data:
            self.update(data)
    
    def __del__(self):
        self.__remove()
    
    def __make_key(self, name):
        assert isinstance(name, basestring)
        name = name.lower()
        if isinstance(name, unicode):
            name = name.encode(self.encoding)
        return name
    
    def __make_text(self, value, canonical=False):
        assert isinstance(value, basestring)
        if canonical:
            value = _canonicalHeaderName(value)
        if isinstance(value, unicode):
            value = value.encode(self.encoding)
        return value
    
    def __iter(self, *args):
        if not args:
            header = self.__head
            while header is not None:
                next = header.next
                yield header
                header = next
        else:
            item = self.__values.get(self.__make_key(args[0]))
            if item is not None:
                header = item[0]
            else:
                header = None
            while header is not None:
                next = header.next_value
                yield header
                header = next
    
    def __remove(self, *args):
        if not args:
            header = self.__head
            while header is not None:
                next = header.next
                header.unlink()
                header = next
            self.__head = None
            self.__tail = None
            self.__values.clear()
        else:
            item = self.__values.pop(self.__make_key(args[0]), None)
            if item is not None:
                header = item[0]
            else:
                header = None
            while header is not None:
                next = header.next_value
                if self.__head is header:
                    self.__head = header.next
                if self.__tail is header:
                    self.__tail = header.prev
                header.unlink()
                header = next
    
    def __append(self, name, value):
        key = self.__make_key(name)
        item = self.__values.get(key)
        if item is None:
            item = self.__values[key] = [None, None]
        header = Header(name, value, prev=self.__tail, prev_value=item[1])
        if header.prev is not None:
            header.prev.next = header
        if header.prev_value is not None:
            header.prev_value.next_value = header
        if item[0] is None:
            item[0] = header
        item[1] = header
        if self.__head is None:
            self.__head = header
        self.__tail = header
    
    def __getitem__(self, name):
        if self.__make_key(name) not in self.__values:
            raise KeyError(name)
        return ', '.join(header.value for header in self.__iter(name))
    
    def __setitem__(self, name, value):
        self.__remove(name)
        if value is None:
            return
        elif isinstance(value, basestring):
            self.__append(name, value)
        else:
            for value in value:
                self.__append(name, value)
    
    def __delitem__(self, name):
        if self.__make_key(name) not in self.__values:
            raise KeyError(name)
        self.__remove(name)
    
    def __iter__(self):
        return self.__iter()
    
    def __contains__(self, name):
        return self.__make_key(name) in self.__values
    
    def iterkeys(self):
        for header in self.__iter():
            yield header.name
    
    def itervalues(self):
        for header in self.__iter():
            yield header.value
    
    def iteritems(self):
        for header in self.__iter():
            yield (header.name, header.value)
    
    def keys(self):
        return list(self.iterkeys())
    
    def values(self):
        return list(self.itervalues())
    
    def items(self):
        return list(self.iteritems())
    
    def getlist(self, name, default=nil):
        if self.__make_key(name) in self.__values:
            return [header.value for header in self.__iter(name)]
        if default is nil:
            return []
        return default
    
    def poplist(self, name, default=nil):
        if self.__make_key(name) in self.__values:
            value = [header.value for header in self.__iter(name)]
            self.__remove(name)
            return value
        if default is nil:
            raise KeyError(name)
        return default
    
    def get(self, name, default=None):
        if self.__make_key(name) in self.__values:
            return ', '.join(self.getlist(name))
        return default
    
    def pop(self, name, default=nil):
        if self.__make_key(name) in self.__values:
            return ', '.join(self.poplist(name))
        if default is nil:
            raise KeyError(name)
        return default
    
    def setdefault(self, name, value):
        if self.__make_key(name) not in self.__values:
            self[name] = value
            if value is None:
                return None
        return ', '.join(self.getlist(name))
    
    def setdefaultlist(self, name, value):
        if self.__make_key(name) not in self.__values:
            self[name] = value
            if value is None:
                return None
        return self.getlist(name)
    
    def add(self, name, value):
        if value is None:
            return
        elif isinstance(value, basestring):
            self.__append(name, value)
        else:
            for value in value:
                self.__append(name, value)
    
    def clear(self):
        self.__remove()
    
    def update(self, data=(), merge=False):
        if hasattr(data, 'iteritems'):
            data = data.iteritems()
        seen = set()
        for name, value in data:
            key = self.__make_key(name)
            if key not in seen:
                if not merge:
                    self.__remove(name)
                seen.add(key)
            if value is None:
                continue
            elif isinstance(value, basestring):
                self.__append(name, value)
            else:
                for value in value:
                    self.__append(name, value)
    
    def toLines(self, lines=None, canonical=False):
        if lines is None:
            lines = []
        for name, value in self.iteritems():
            name = self.__make_text(name, canonical=canonical)
            value = self.__make_text(value)
            lines.append("%s: %s\r\n" % (name, value))
        return lines
    
    def toString(self, canonical=False):
        return ''.join(self.toLines(canonical=canonical))
    
    def __str__(self):
        return self.toString()
    
    def __repr__(self):
        return "Headers({%s})" % ', '.join("%r: %r" % (name, value) for (name, value) in self.iteritems())
    
    def parseClear(self):
        self.__partialHeader = None
    
    def parseFlush(self):
        if self.__partialHeader:
            header = '\r\n'.join(self.__partialHeader)
            self.__partialHeader = None
            parts = header.split(':', 1)
            if len(parts) != 2:
                raise HTTPDataError("header must be in 'name: value' format")
            name = parts[0].rstrip()
            value = parts[1].strip()
            if not name:
                raise HTTPDataError("header must be in 'name: value' format")
            self.add(name, value)
    
    def parseLine(self, line):
        if not line or not line[0] in ' \t':
            self.parseFlush()
            if line:
                self.__partialHeader = [line]
        else:
            if self.__partialHeader:
                self.__partialHeader.append(line)
        return line and True or False
