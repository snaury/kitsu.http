import eventlet
eventlet.monkey_patch()
import os
execfile(os.path.join(os.path.dirname(__file__), 'setup.py'))
