"""Agent 团队协作端点（批10）：启动 / 轮询 / 列表。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.security.auth import get_current_user
from app.services import team_service
from app.services.team_service import run_team_bg

router = APIRouter()


class TeamStartIn(BaseModel):
    goal: str = Field(min_length=2, max_length=1000)


@router.post("/start")
async def start_team(
    body: TeamStartIn,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await team_service.start_team_run(db, str(user.id), body.goal)
    asyncio.create_task(run_team_bg(row.id))
    return {"id": row.id, "status": row.status}


@router.get("/{run_id}")
async def get_team(
    run_id: str,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await team_service.get_run(db, str(user.id), run_id)
    if not row:
        raise HTTPException(status_code=404, detail="团队任务不存在")
    return _dump(row)


@router.get("")
async def list_teams(
    limit: int = Query(20, ge=1, le=50),
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await team_service.list_runs(db, str(user.id), limit)
    return {"items": [_dump(r, brief=True) for r in rows]}


def _dump(r: Any, brief: bool = False) -> dict:
    d = {
        "id": r.id,
        "goal": r.goal,
        "status": r.status,
        "members": r.members or [],
        "steps": r.steps or [],
        "error": r.error,
        "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
    }
    if not brief:
        d["final_report"] = r.final_report
    return d
