import sys as _sys

from app.applications import asmr_ingest as _impl

_sys.modules[__name__] = _impl
