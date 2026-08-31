import sys as _sys

from app.applications import web_search as _impl

_sys.modules[__name__] = _impl
