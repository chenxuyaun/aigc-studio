import sys as _sys

from app.applications import prompt_tools as _impl

_sys.modules[__name__] = _impl
