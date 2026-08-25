"""AI 成长足迹端点（批8+9）：日记分页 / 记忆列表与删除 / 手动反思。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.growth import GrowthDiary, MemoryEntry
from app.security.auth import get_current_user
from app.services import growth_service
from app.services.growth_service import reflect_session_bg

router = APIRouter()


@router.get("/diary")
async def list_diary(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """成长日记时间线（新→旧，带 envelope 分页）。"""
    total = (
        await db.execute(
            select(func.count()).select_from(GrowthDiary).where(GrowthDiary.user_id == user.id)
        )
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(GrowthDiary)
                .where(GrowthDiary.user_id == user.id)
                .order_by(GrowthDiary.created_at.desc(), GrowthDiary.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "session_id": r.session_id,
                "summary": r.summary,
                "lessons": r.lessons or [],
                "highlights": r.highlights or [],
                "msg_count": r.msg_count,
                "created_at": (r.created_at.isoformat() + "Z") if r.created_at else None,
            }
            for r in rows
        ],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


@router.get("/memories")
async def list_memories(
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """「AI 记得你」记忆列表（新→旧）。"""
    rows = (
        (
            await db.execute(
                select(MemoryEntry)
                .where(MemoryEntry.user_id == user.id)
                .order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "kind": r.kind,
                "content": r.content,
                "updated_at": (r.updated_at.isoformat() + "Z") if r.updated_at else None,
            }
            for r in rows
        ]
    }


class MemoryDeleteIn(BaseModel):
    ids: list[str]


@router.post("/memories/delete")
async def delete_memories(
    body: MemoryDeleteIn,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not body.ids:
        raise HTTPException(status_code=422, detail="ids 不能为空")
    res = await db.execute(
        MemoryEntry.__table__.delete().where(
            MemoryEntry.user_id == user.id, MemoryEntry.id.in_(body.ids[:50])
        )
    )
    await db.commit()
    return {"deleted": int(res.rowcount or 0)}


class ReflectIn(BaseModel):
    session_id: str


@router.post("/reflect")
async def manual_reflect(
    body: ReflectIn,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动触发一次会话反思（前端对话页「总结这次对话」按钮）。"""
    result = await growth_service.reflect_session(db, str(user.id), body.session_id)
    if result is None:
        return {"ok": False, "reason": "对话太短或暂无可反思的新内容"}
    return {"ok": True, **result}


@router.post("/reflect-bg")
async def background_reflect(
    body: ReflectIn,
    user: Any = Depends(get_current_user),
) -> dict:
    """fire-and-forget 反思：agent_chat 流结束后前端调用，立即返回。"""
    import asyncio

    asyncio.create_task(reflect_session_bg(str(user.id), body.session_id))
    return {"ok": True}
