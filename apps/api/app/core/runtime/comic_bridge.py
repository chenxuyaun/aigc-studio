import sys as _sys

# P4-2：Comic 桥已迁 app.applications.comic.bridge；本路径保留 import 兼容（同一模块对象）。
from app.applications.comic import bridge as _impl

_sys.modules[__name__] = _impl
