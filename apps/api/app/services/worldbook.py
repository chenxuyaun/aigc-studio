import sys as _sys

from app.applications import worldbook as _impl

_sys.modules[__name__] = _impl
