import gevent.monkey
gevent.monkey.patch_all()
import os
execfile(os.path.join(os.path.dirname(__file__), 'setup.py'))
