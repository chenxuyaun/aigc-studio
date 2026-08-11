import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import get_db
from app.models.generation_task import GenerationTask
from app.models.user import User
from app.security.auth import get_current_user

router = APIRouter()


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    # 非管理员仅统计自己的任务
    scope: list[ColumnElement[bool]] = []
    if user.role != "admin":
        scope = [GenerationTask.user_id == user.id]

    async def _count(*extra: ColumnElement[bool]) -> int:
        q = select(func.count(GenerationTask.id))
        for clause in (*scope, *extra):
            q = q.where(clause)
        return (await db.execute(q)).scalar() or 0

    total = await _count()
    succeeded = await _count(GenerationTask.status == "succeeded")
    failed = await _count(GenerationTask.status == "failed")
    text_count = await _count(GenerationTask.task_type == "text")
    image_count = await _count(GenerationTask.task_type == "image")
    video_count = await _count(GenerationTask.task_type == "video")
    audio_count = await _count(GenerationTask.task_type == "audio")

    # 近 7 天每日任务数（逐日 COUNT，避免 SQLite/MySQL 日期函数方言差异）
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    trend_7d: list[dict[str, object]] = []
    for i in range(6, -1, -1):
        start = day_start - timedelta(days=i)
        q = select(func.count(GenerationTask.id)).where(
            GenerationTask.created_at >= start,
            GenerationTask.created_at < start + timedelta(days=1),
        )
        if scope:
            q = q.where(*scope)
        n = (await db.execute(q)).scalar() or 0
        trend_7d.append({"date": start.date().isoformat(), "count": n})

    recent_q = select(GenerationTask)
    if scope:
        recent_q = recent_q.where(*scope)
    recent = (
        (await db.execute(recent_q.order_by(GenerationTask.created_at.desc()).limit(5)))
        .scalars()
        .all()
    )

    return {
        "success": True,
        "data": {
            "total_tasks": total,
            "succeeded": succeeded,
            "failed": failed,
            "text_count": text_count,
            "image_count": image_count,
            "video_count": video_count,
            "audio_count": audio_count,
            "trend_7d": trend_7d,
            "recent_tasks": [
                {
                    "id": t.id,
                    "task_type": t.task_type,
                    "status": t.status,
                    "progress": t.progress,
                    "model": t.model,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in recent
            ],
        },
    }


@router.get("/inspections/latest")
async def latest_inspection(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """最近一份每日巡检报告（若无报告返回 null）。仅管理员可见。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可查看巡检报告")
    from app.models.inspection_report import InspectionReport

    row = (
        await db.execute(
            select(InspectionReport).order_by(InspectionReport.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return {"report": None}
    try:
        data = json.loads(row.content)
    except ValueError, TypeError:
        data = {"raw": row.content[:1000]}
    return {"report": data, "created_at": row.created_at.isoformat() if row.created_at else None}
