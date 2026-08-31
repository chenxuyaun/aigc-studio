import sys as _sys

from app.applications import character_distill as _impl

_sys.modules[__name__] = _impl
