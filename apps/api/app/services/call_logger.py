import sys as _sys

from app.applications import call_logger as _impl

_sys.modules[__name__] = _impl
