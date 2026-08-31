import sys as _sys

from app.applications import memory_inject as _impl

_sys.modules[__name__] = _impl
