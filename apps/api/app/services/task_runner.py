import sys as _sys

from app.applications import task_runner as _impl

_sys.modules[__name__] = _impl
