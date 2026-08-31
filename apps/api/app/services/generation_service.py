"""Task 创建服务（P0-3 薄 facade）。

P0-3 后：实际实现已迁到 `app.core.runtime.task_lifecycle.create_media_task`。
本模块**只**保留 wrapper 以兼容现有 import 路径（路由层 `from app.services.generation_service import create_media_task`）。
P 阶段清理时如无外部依赖可删除。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime.task_lifecycle import _dispatch, create_media_task

__all__ = ["create_media_task", "_dispatch"]
