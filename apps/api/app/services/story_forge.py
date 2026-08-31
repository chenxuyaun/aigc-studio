import sys as _sys

from app.applications import story_forge as _impl

_sys.modules[__name__] = _impl
