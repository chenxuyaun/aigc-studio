"""定时创作服务（P0-8 薄 facade）。

P0-8 后：实际实现已迁到 `app.core.runtime.scheduler.scheduled_creator`。
本模块**只**保留 wrapper 以兼容现有 import 路径。
"""
from app.core.runtime.scheduler import (  # 兼容
    compute_next_run_at,
    enqueue_run,
    run_due_schedules,
)

__all__ = ["compute_next_run_at", "enqueue_run", "run_due_schedules"]
