import sys as _sys

from app.applications import agent_chat as _impl

_sys.modules[__name__] = _impl
