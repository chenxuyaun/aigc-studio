"""调用日志（P0-6 薄 facade）。

P0-6 后：实际实现已迁到 `app.core.runtime.audit.call_log.log_call`。
本模块**只**保留 wrapper 以兼容现有 import 路径。
"""
from app.core.runtime.audit.call_log import log_call  # noqa: F401  # 兼容

__all__ = ["log_call"]
