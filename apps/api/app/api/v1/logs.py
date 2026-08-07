from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.ai_call_log import AiCallLog
from app.models.user import User
from app.security.auth import require_role

router = APIRouter()


@router.get("/")
async def list_call_logs(
    task_type: str = Query(default="", description="text / image / audio / video"),
    status: str = Query(default="", description="succeeded / fallback / failed"),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    """Provider 调用日志（管理员）：最近 limit 条，可按类型/状态过滤。"""
    stmt = select(AiCallLog).order_by(AiCallLog.created_at.desc()).limit(limit)
    if task_type:
        stmt = stmt.where(AiCallLog.task_type == task_type)
    if status:
        stmt = stmt.where(AiCallLog.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "task_id": r.task_id,
            "task_type": r.task_type,
            "provider": r.provider,
            "model": r.model,
            "status": r.status,
            "error_message": r.error_message,
            "duration_ms": r.duration_ms,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
