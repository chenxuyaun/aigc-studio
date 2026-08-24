"""AI 调度大厅会话云同步端点（saiOS v2 P1）。

前端 useChatSessions 写穿：挂载 GET 全量合并；变更防抖 PUT 单会话 upsert。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.chat_session import ChatSession
from app.security.auth import get_current_user
from app.models.user import User

# 挂载点：v1/__init__.py 里 include_router(prefix="/chat") → 最终 /api/v1/chat/sessions
router = APIRouter(tags=["chat"])


class ChatSessionSync(BaseModel):
    """单个会话同步载荷（全量）。"""

    name: str = Field(default="新会话", max_length=120)
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=400)
    group: str | None = Field(default=None, max_length=60)
    archived: bool = False
    updated_at: int = 0  # 前端 epoch ms（用于排序展示，服务端以 server 时间入库）


class ChatSessionOut(ChatSessionSync):
    id: str


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _to_out(row: ChatSession) -> ChatSessionOut:
    return ChatSessionOut(
        id=row.id,
        name=row.name,
        messages=row.messages or [],
        group=row.session_group,
        archived=bool(row.archived),
        updated_at=int(row.updated_at.timestamp() * 1000) if row.updated_at else 0,
    )


@router.get("")
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionOut]:
    rows = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.user_id == user.id)
                .order_by(ChatSession.updated_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(r) for r in rows]


@router.put("/{session_id}")
async def upsert_session(
    session_id: str,
    payload: ChatSessionSync,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    row = await db.get(ChatSession, session_id)
    if row is not None and row.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    if row is None:
        if len(session_id) > 40:
            raise HTTPException(status_code=400, detail="非法会话 id")
        row = ChatSession(id=session_id, user_id=user.id)
        db.add(row)
    row.name = payload.name or "新会话"
    row.messages = payload.messages
    row.session_group = payload.group or None
    row.archived = payload.archived
    row.updated_at = _now()
    await db.commit()
    return {"ok": True, "id": session_id}


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    row = await db.get(ChatSession, session_id)
    if row is None:
        return {"ok": True}
    if row.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
