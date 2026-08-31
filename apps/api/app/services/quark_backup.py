import sys as _sys

from app.applications import quark_backup as _impl

_sys.modules[__name__] = _impl
