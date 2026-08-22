"""定时创作（Scheduled Creations）API：创建/列表/详情/更新/删除/立即入队。"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.scheduled_creation import ScheduledCreation
from app.models.user import User
from app.security.auth import get_current_user
from app.services import schedule_service

router = APIRouter()


class ScheduleCreateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=5000)
    task_type: str = Field(default="text", pattern="^(text|image|audio)$")
    schedule_type: str = Field(pattern="^(daily|interval)$")
    daily_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    interval_hours: int | None = Field(default=None, ge=1, le=24 * 365)

    @field_validator("daily_time", "schedule_type", "task_type", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class ScheduleUpdateRequest(BaseModel):
    prompt: str | None = Field(default=None, min_length=1, max_length=5000)
    task_type: str | None = Field(default=None, pattern="^(text|image|audio)$")
    schedule_type: str | None = Field(default=None, pattern="^(daily|interval)$")
    daily_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    interval_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    is_enabled: bool | None = None


def _parse_time(hhmm: str | None) -> time | None:
    if not hhmm:
        return None
    hour, minute = hhmm.split(":")
    return time(int(hour), int(minute))


def _fmt_time(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t is not None else None


def _schedule_dict(s: ScheduledCreation) -> dict[str, Any]:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "prompt": s.prompt,
        "task_type": s.task_type,
        "schedule_type": s.schedule_type,
        "daily_time": _fmt_time(s.daily_time),
        "interval_hours": s.interval_hours,
        "is_enabled": bool(s.is_enabled),
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "last_result_task_id": s.last_result_task_id,
        "last_error": s.last_error or "",
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _validate_schedule_config(
    schedule_type: str, daily_time: str | None, interval_hours: int | None
) -> None:
    if schedule_type == "daily" and not daily_time:
        raise HTTPException(
            status_code=400, detail="schedule_type=daily 时必须提供 daily_time (HH:MM)"
        )
    if schedule_type == "interval" and (not interval_hours or interval_hours <= 0):
        raise HTTPException(
            status_code=400, detail="schedule_type=interval 时必须提供 interval_hours>0"
        )


async def _get_owned_schedule(
    schedule_id: str, db: AsyncSession, user: User
) -> ScheduledCreation:
    result = await db.execute(
        select(ScheduledCreation).where(ScheduledCreation.id == schedule_id)
    )
    s = result.scalar_one_or_none()
    if not s or (s.user_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="定时创作不存在")
    return s


def _create_schedule_obj(
    user_id: str, req: ScheduleCreateRequest
) -> ScheduledCreation:
    _validate_schedule_config(req.schedule_type, req.daily_time, req.interval_hours)
    next_run_at = schedule_service.compute_next_run_at(
        req.schedule_type, _parse_time(req.daily_time), req.interval_hours
    )
    return ScheduledCreation(
        user_id=user_id,
        prompt=req.prompt,
        task_type=req.task_type,
        schedule_type=req.schedule_type,
        daily_time=_parse_time(req.daily_time),
        interval_hours=req.interval_hours,
        is_enabled=True,
        next_run_at=next_run_at,
    )


@router.post("")
async def create_schedule(
    req: ScheduleCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """创建定时创作（自动计算 next_run_at）。"""
    s = _create_schedule_obj(user.id, req)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return {"success": True, "data": _schedule_dict(s)}


@router.get("")
async def list_schedules(
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """当前用户的定时创作列表（created_at desc）。"""
    result = await db.execute(
        select(ScheduledCreation)
        .where(ScheduledCreation.user_id == user.id)
        .order_by(ScheduledCreation.created_at.desc())
        .limit(limit)
    )
    items = result.scalars().all()
    return {"success": True, "data": [_schedule_dict(s) for s in items]}


@router.get("/{schedule_id}")
async def get_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """定时创作详情。"""
    s = await _get_owned_schedule(schedule_id, db, user)
    return {"success": True, "data": _schedule_dict(s)}


@router.put("/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    req: ScheduleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """更新定时创作（prompt/开关/时间），并按最新配置重算 next_run_at。"""
    s = await _get_owned_schedule(schedule_id, db, user)
    if req.prompt is not None:
        s.prompt = req.prompt
    if req.task_type is not None:
        s.task_type = req.task_type
    if req.is_enabled is not None:
        s.is_enabled = req.is_enabled

    # 时间相关字段更新：合并到当前记录后再校验 + 重算 next_run_at
    if req.schedule_type is not None:
        s.schedule_type = req.schedule_type
    if req.daily_time is not None:
        s.daily_time = _parse_time(req.daily_time)
    if req.interval_hours is not None:
        s.interval_hours = req.interval_hours

    if (
        req.schedule_type is not None
        or req.daily_time is not None
        or req.interval_hours is not None
    ):
        _validate_schedule_config(
            s.schedule_type, _fmt_time(s.daily_time), s.interval_hours
        )
        s.next_run_at = schedule_service.compute_next_run_at(
            s.schedule_type, s.daily_time, s.interval_hours
        )

    await db.commit()
    await db.refresh(s)
    return {"success": True, "data": _schedule_dict(s)}


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """删除定时创作。"""
    s = await _get_owned_schedule(schedule_id, db, user)
    await db.delete(s)
    await db.commit()
    return {"success": True, "data": None}


@router.post("/{schedule_id}/run-now")
async def run_now(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """立即入队一次生成任务（不论开关状态），返回生成任务记录。"""
    s = await _get_owned_schedule(schedule_id, db, user)
    task = await schedule_service.enqueue_run(db, s)
    s.last_run_at = datetime.now(UTC)
    s.last_result_task_id = task.id
    s.last_error = None
    await db.commit()
    await db.refresh(s)
    return {
        "success": True,
        "data": {
            "task_id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "schedule": _schedule_dict(s),
        },
    }
