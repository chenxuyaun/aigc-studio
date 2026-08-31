import sys as _sys

from app.applications import agentlist_ingest as _impl

_sys.modules[__name__] = _impl
