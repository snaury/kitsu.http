import warnings
warnings.warn("kitsu.http.sockets is deprecated, please use kitsu.http.client instead", DeprecationWarning)
import sys
from kitsu.http import client
sys.modules[__name__] = client
