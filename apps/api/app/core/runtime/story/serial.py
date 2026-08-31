"""Core Runtime - Story 自动连载排期 CRUD（P1-3 从 api/v1/story.py 抽离，逐字搬运）。

SerialSchedule 直连 DB 的薄查询层。建排期前校验项目归属（story_forge.get_project）。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.serial_schedule import SerialSchedule
from app.services import story_forge
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def schedule_list(
    db: AsyncSession,
    user_id: str,
    project_id: str,
) -> dict[str, Any]:
    rows = (
        (
            await db.execute(
                select(SerialSchedule).where(
                    SerialSchedule.project_id == project_id,
                    SerialSchedule.user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": s.id,
                "project_id": s.project_id,
                "interval_minutes": s.interval_minutes,
                "batch_size": s.batch_size,
                "next_run_at": str(s.next_run_at) if s.next_run_at else "",
                "chapter_count": s.chapter_count,
                "status": s.status,
                "mode": s.mode,
                "last_run_at": str(s.last_run_at) if s.last_run_at else "",
                "error_message": s.error_message,
            }
            for s in rows
        ]
    }


async def schedule_create(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    *,
    interval_minutes: int,
    batch_size: int,
    mode: str,
    status: str,
) -> dict[str, Any]:
    p = await story_forge.get_project(db, user_id, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    now = datetime.now(UTC)
    s = SerialSchedule(
        project_id=project_id,
        user_id=user_id,
        interval_minutes=interval_minutes,
        batch_size=batch_size,
        mode=mode,
        status=status,
        next_run_at=now + timedelta(minutes=interval_minutes),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return {
        "ok": True,
        "schedule": {
            "id": s.id,
            "project_id": s.project_id,
            "interval_minutes": s.interval_minutes,
            "next_run_at": str(s.next_run_at),
            "status": s.status,
            "mode": s.mode,
        },
    }


async def schedule_update(
    db: AsyncSession,
    user_id: str,
    schedule_id: str,
    *,
    interval_minutes: int,
    batch_size: int,
    mode: str,
    status: str,
) -> dict[str, Any]:
    s = (
        await db.execute(
            select(SerialSchedule).where(
                SerialSchedule.id == schedule_id, SerialSchedule.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="调度不存在")
    s.interval_minutes = interval_minutes
    s.batch_size = batch_size
    s.mode = mode
    s.status = status
    await db.commit()
    return {"ok": True}


async def schedule_delete(
    db: AsyncSession,
    user_id: str,
    schedule_id: str,
) -> dict[str, Any]:
    s = (
        await db.execute(
            select(SerialSchedule).where(
                SerialSchedule.id == schedule_id, SerialSchedule.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="调度不存在")
    await db.delete(s)
    await db.commit()
    return {"ok": True}
