__all__ = [
    'Parser',
    'LineParser',
]

class Parser(object):
    """Abstract data parser"""
    done = False
    cache = ''
    
    def clear(self):
        """Clears and returns current cache"""
        data, self.cache = self.cache, ''
        return data
    
    def prepend(self, data):
        """Prepend data to cache"""
        if data:
            self.cache = data + self.cache
    
    def append(self, data):
        """Append data to cache"""
        if data:
            self.cache = self.cache + data
    
    def parse(self, data):
        """Feed chunk of data to parser. Returns parsed bits if available."""
        if data:
            self.cache += data
        if self.done:
            return ()
        output = []
        while self.cache and not self.done:
            data, self.cache = self.cache, ''
            bits = self.parseRaw(data)
            if bits is None:
                # parseRaw has not enough data
                break
            output.extend(bits)
        return output
    
    def finish(self):
        """Tell parser there is no more data. Returns parsed bits if available."""
        self.done = True
        return ()
    
    def parseRaw(self, data):
        """Called by parse with current data chunk"""
        raise NotImplementedError

class LineParser(Parser):
    """Line based parser"""
    
    linemode = True
    
    def parseRaw(self, data):
        """Parses and dispatches raw data"""
        if self.linemode:
            pos = data.find('\n')
            if pos < 0:
                self.prepend(data)
                return None
            if pos > 0 and data[pos-1] == '\r':
                line, data = data[:pos-1], data[pos+1:]
            else:
                line, data = data[:pos], data[pos+1:]
            self.prepend(data)
            return self.parseLine(line)
        else:
            return self.parseData(data)
    
    def setLineMode(self, extra=''):
        """Sets parsing to line mode"""
        if extra:
            self.prepend(extra)
        self.linemode = True
    
    def setDataMode(self, extra=''):
        """Sets parsing to data mode"""
        if extra:
            self.prepend(extra)
        self.linemode = False
    
    def parseLine(self, line):
        """Called by parseRaw with current line"""
        raise NotImplementedError
    
    def parseData(self, data):
        """Called by parseRaw with current data"""
        raise NotImplementedError
