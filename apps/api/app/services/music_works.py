import sys as _sys

from app.applications import music_works as _impl

_sys.modules[__name__] = _impl
