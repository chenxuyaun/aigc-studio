"""Core Runtime - Task 进度 / 取消检查。

从 services/task_runner.py 拆出：
- _PROGRESS_STEPS：任务进度百分比常量
- _is_cancelled：长 await 之后检查 DB 状态（防止覆盖终态）

P0 边界：task_runner.py 通过 `from app.core.runtime.task import ...` 使用。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_task import GenerationTask

# 任务执行期间上报的进度百分比（saiOS UI 用）。
PROGRESS_STEPS: tuple[int, ...] = (10, 35, 60, 85)


async def is_cancelled(db: AsyncSession, task_id: str) -> bool:
    """从 DB 重读任务状态，用于长 await 之后检查取消（防止覆盖终态）。"""
    try:
        row = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
        return row is None or row.status == "cancelled"
    except Exception:
        return False
