"""创作目标模式（Goal Mode）API：设目标 → AI 自主拆解执行 → 成果总结。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.creation_goal import CreationGoal
from app.models.user import User
from app.security.auth import get_current_user
from app.services import goal_service

router = APIRouter()

_GOAL_LIST_LIMIT = 50


class GoalCreateRequest(BaseModel):
    goal_text: str = Field(min_length=1, max_length=5000)


def _goal_dict(g: CreationGoal) -> dict[str, Any]:
    return {
        "id": g.id,
        "user_id": g.user_id,
        "goal_text": g.goal_text,
        "status": g.status,
        "result_summary": g.result_summary or "",
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
    }


async def _get_owned_goal(goal_id: str, db: AsyncSession, user: User) -> CreationGoal:
    result = await db.execute(select(CreationGoal).where(CreationGoal.id == goal_id))
    goal = result.scalar_one_or_none()
    if not goal or (goal.user_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="目标不存在")
    return goal


@router.post("")
async def create_goal(
    req: GoalCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """创建创作目标（status=planned）。"""
    goal = CreationGoal(goal_text=req.goal_text, user_id=user.id, status="planned")
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return {"success": True, "data": _goal_dict(goal)}


@router.post("/{goal_id}/run")
async def run_goal(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """执行目标：复用 agent_chat 工具循环（拆解计划 → 逐步调 MCP 工具 → 成果总结），
    同步跑完（非 SSE），把终态写回 goal 并返回。超时保护 180s。"""
    goal = await _get_owned_goal(goal_id, db, user)
    if goal.status == "running":
        raise HTTPException(status_code=409, detail="目标正在执行中，请稍后再试")
    goal = await goal_service.run_goal(db, goal)
    return {"success": True, "data": _goal_dict(goal)}


@router.get("")
async def list_goals(
    limit: int = Query(default=_GOAL_LIST_LIMIT, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """当前用户的创作目标列表（created_at desc，默认 50）。"""
    query = select(CreationGoal).where(CreationGoal.user_id == user.id)
    result = await db.execute(
        query.order_by(CreationGoal.created_at.desc()).limit(limit)
    )
    goals = result.scalars().all()
    return {"success": True, "data": [_goal_dict(g) for g in goals]}


@router.get("/{goal_id}")
async def get_goal(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """目标详情。"""
    goal = await _get_owned_goal(goal_id, db, user)
    return {"success": True, "data": _goal_dict(goal)}
