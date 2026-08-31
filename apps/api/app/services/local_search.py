import sys as _sys

from app.applications import local_search as _impl

_sys.modules[__name__] = _impl
