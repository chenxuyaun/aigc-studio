import sys as _sys

from app.applications import provider_resolver as _impl

_sys.modules[__name__] = _impl
