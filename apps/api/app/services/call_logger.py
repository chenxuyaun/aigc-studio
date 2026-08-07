"""Provider 调用日志：写库不阻塞主流程，失败仅记 structlog。"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.ai_call_log import AiCallLog

logger = structlog.get_logger()


async def log_call(
    *,
    task_id: str = "",
    task_type: str = "",
    provider: str = "",
    model: str = "",
    status: str = "succeeded",
    error_message: str = "",
    duration_ms: int = 0,
    db: AsyncSession | None = None,
) -> None:
    """记录一次 Provider 调用。传入 db 则复用事务；否则自建会话（后台任务用）。"""
    row = AiCallLog(
        task_id=task_id[:36],
        task_type=task_type[:20],
        provider=provider[:40],
        model=model[:100],
        status=status,
        error_message=(error_message or "")[:4000],
        duration_ms=int(duration_ms),
    )
    try:
        if db is not None:
            db.add(row)
            await db.commit()
        else:
            async with AsyncSessionLocal() as own_db:
                own_db.add(row)
                await own_db.commit()
    except Exception:
        logger.warning("ai_call_log_failed", error="写入调用日志失败", exc_info=True)
