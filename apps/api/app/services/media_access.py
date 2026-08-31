import sys as _sys

from app.applications import media_access as _impl

_sys.modules[__name__] = _impl
