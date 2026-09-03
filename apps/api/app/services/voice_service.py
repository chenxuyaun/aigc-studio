import sys as _sys

from app.applications import voice_service as _impl

_sys.modules[__name__] = _impl
