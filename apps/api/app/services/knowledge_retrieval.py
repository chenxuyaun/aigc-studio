import sys as _sys

from app.applications import knowledge_retrieval as _impl

_sys.modules[__name__] = _impl
