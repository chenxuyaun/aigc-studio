"""Mission 任务总控端点：给目标，自动拆解执行（AGI Orchestrator 阶段 1）。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.security.auth import get_current_user
from app.services import mission_service

router = APIRouter(prefix="/mission", tags=["mission"])


class MissionRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=800)


@router.post("")
async def run_mission(
    req: MissionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """任务总控：目标 → 自动拆解为多步计划 → 串行执行 → 汇总 → 沉淀教训。"""
    result = await mission_service.run_mission(db, user.id, req.goal.strip())
    result["model"] = "auto"
    return result


@router.get("/history")
async def mission_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """任务历史 + 沉淀的教训（平台「记住你」：长期协作记忆）。"""
    from sqlalchemy import select

    from app.models.mission_lesson import MissionLesson

    lessons = (
        (
            await db.execute(
                select(MissionLesson)
                .where(MissionLesson.user_id == user.id)
                .order_by(MissionLesson.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    runs = await mission_service.list_runs(db, user.id, limit=20)
    return {
        "lessons": [
            {
                "id": item.id,
                "goal": item.goal,
                "lesson": item.lesson,
                "created_at": str(item.created_at) if item.created_at else "",
            }
            for item in lessons
        ],
        "runs": runs,
    }


@router.get("/runs/{run_id}")
async def mission_run_detail(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """单次任务会话完整回看（长期协作记忆）。"""
    run = await mission_service.get_run(db, user.id, run_id)
    if run is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="会话不存在")
    return run


@router.post("/runs/{run_id}/reuse")
async def mission_run_reuse(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """复用历史会话：用同一目标再跑一次（可回看可复用）。"""
    run = await mission_service.get_run(db, user.id, run_id)
    if run is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="会话不存在")
    return await mission_service.run_mission(db, user.id, str(run["goal"]))


@router.get("/agents")
async def mission_agents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """可用 Agent 列表（Multi-Agent Orchestration：规划时从中选择执行单元）。"""
    agents = await mission_service._available_agents(db, user.id)
    return {"agents": agents}


@router.get("/agent-runs")
async def agent_runs_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Agent 运行留痕（State）：每个 Agent 被调度执行的历史。"""
    from sqlalchemy import select

    from app.models.agent_run import AgentRun

    rows = (
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.user_id == user.id)
                .order_by(AgentRun.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return {
        "runs": [
            {
                "id": r.id,
                "agent_id": r.agent_id,
                "goal": r.goal,
                "result": r.result[:200],
                "status": r.status,
                "created_at": str(r.created_at) if r.created_at else "",
            }
            for r in rows
        ]
    }


@router.get("/runs/{run_id}/artifacts/zip")
async def mission_artifacts_zip(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """项目交付：把任务会话中的代码产物打包成 zip 下载。"""
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    run = await mission_service.get_run(db, user.id, run_id)
    if run is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="会话不存在")
    files: list[dict[str, str]] = []
    for r in run.get("results") or []:
        for f in r.get("code") or []:
            if isinstance(f, dict) and f.get("path") and f.get("content"):
                files.append(f)
    if not files:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="该会话没有代码产物")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen: set[str] = set()
        for f in files:
            path = str(f["path"]).replace("\\", "/").lstrip("/") or "file.txt"
            if path in seen:
                path = f"{path.rsplit('.', 1)[0]}-{len(seen)}.{path.rsplit('.', 1)[-1]}"
            seen.add(path)
            zf.writestr(path, str(f["content"]))
    buf.seek(0)
    filename = f"mission-{run_id[:8]}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class MissionExecRequest(BaseModel):
    """手动执行会话中的代码产物（仅 .py；容器内受限运行，timeout+截断）。"""

    path: str = Field(min_length=1, max_length=200)


@router.post("/runs/{run_id}/exec")
async def mission_exec(
    run_id: str,
    req: MissionExecRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """执行沙盒：用户手动触发 .py 产物在容器内运行（timeout 15s，输出截断）。"""
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    from fastapi import HTTPException

    run = await mission_service.get_run(db, user.id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    target = None
    for r in run.get("results") or []:
        for f in r.get("code") or []:
            if isinstance(f, dict) and str(f.get("path") or "") == req.path:
                target = f
                break
    if target is None:
        raise HTTPException(status_code=404, detail="文件中不存在")
    content = str(target.get("content") or "")
    if not req.path.endswith(".py"):
        return {"ok": False, "output": "仅支持 .py 文件执行；其他文件请下载后在本地运行"}
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / req.path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, str(fp)],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=td,
            )
            out = (proc.stdout or "")[-2000:]
            if proc.stderr:
                out += f"\n[stderr]\n{(proc.stderr or '')[-1000:]}"
            ok = proc.returncode == 0
        except subprocess.TimeoutExpired:
            out, ok = "执行超时（15s 上限）", False
    return {"ok": ok, "output": out or "（无输出）"}


@router.get("/profile")
async def mission_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """成长档案：平台对用户的了解（偏好聚合 + LLM 画像）。"""
    from app.services.profile_service import (
        aggregate_preferences,
        summarize_profile,
    )

    prefs = await aggregate_preferences(db, user.id)
    summary = await summarize_profile(db, user.id)
    return {"preferences": prefs, "profile": summary}
