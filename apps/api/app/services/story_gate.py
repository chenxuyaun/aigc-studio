import sys as _sys

from app.applications import story_gate as _impl

_sys.modules[__name__] = _impl
