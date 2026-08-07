"""上游状态聚合 + 注册批次调度（grok2api / 注册机 / cpa）。

- GET  /api/v1/upstream/status：聚合展示
  - grok2api 账号池（总数/active/最新注册）
  - 注册机运行状态（phase/本轮成功失败）
  - grok 图片可用性（轻量探测，带 10s 缓存避免每次生成图片）
  - cpa 在线状态
- POST /api/v1/upstream/register：触发注册机跑一批注册，并记录为
  generation_tasks(task_type="register")，由 celery 任务执行 + 更新结果。
"""

from __future__ import annotations

import json
import os
import time

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.generation_task import GenerationTask
from app.models.user import User
from app.schemas.generation import TaskResponse
from app.security.auth import get_current_user

router = APIRouter()

logger = structlog.get_logger("aigc.upstream")

# 注册批次安全上限（单批最长 4h 任务，防误触/滥用）
MAX_REGISTER_RUN_COUNT = 20

GROK_ADMIN = os.environ.get("GROK_ADMIN_BASE", "http://host.docker.internal:8000")
REGISTER_BASE = os.environ.get("REGISTER_BASE", "http://host.docker.internal:6657")
CPA_BASE = os.environ.get("CPA_BASE", "http://host.docker.internal:8317")

# 探活缓存：grok 图片探测较慢（可能 30-90s），10 分钟内复用结果
_grok_probe_cache: dict[str, object] = {"at": 0.0, "ok": False, "error": ""}


def _register_internal_key() -> str:
    key = os.environ.get("REGISTER_INTERNAL_KEY", "")
    if key:
        return key
    for p in ("/register-data/internal-api-key", "/app/register-data/internal-api-key"):
        if os.path.exists(p):
            try:
                return open(p, encoding="utf-8").read().strip()
            except Exception:
                pass
    return ""


async def _grok_account_pool() -> dict[str, object]:
    """grok2api 账号池统计（管理 API，凭据走注册机 config.json fallback）。"""
    import json as _json

    user = os.environ.get("GROK2API_ADMIN_USERNAME", "")
    password = os.environ.get("GROK2API_ADMIN_PASSWORD", "")
    if not user or not password:
        cfg = os.environ.get(
            "GROK_REGISTER_CONFIG",
            r"C:\Users\yuesh\.meituan-catpaw\5667331509\desk_default_workspace"
            r"\grok-register\GrokRegisterAgent\register\config.json",
        )
        try:
            with open(cfg, encoding="utf-8") as f:  # noqa: ASYNC230 - 启动期小文件
                c = _json.load(f)
            user = str(c.get("grok2api_username") or "")
            password = str(c.get("grok2api_password") or "")
        except Exception:
            pass
    if not user or not password:
        return {"total": 0, "active": 0, "error": "未配置 grok2api 管理凭据"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{GROK_ADMIN}/api/admin/v1/auth/login",
                json={"username": user, "password": password},
                timeout=20,
            )
            if r.status_code != 200:
                return {"total": 0, "active": 0, "error": f"登录失败 {r.status_code}"}
            token = r.json()["data"]["tokens"]["accessToken"]
            r2 = await client.get(
                f"{GROK_ADMIN}/api/admin/v1/accounts",
                params={"page": 1, "pageSize": 1},
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            total = int(r2.json()["data"].get("total") or 0)
            return {"total": total, "active": total, "error": ""}
    except Exception as exc:
        return {"total": 0, "active": 0, "error": str(exc)[:120]}


async def _grok_image_probe(force: bool = False) -> dict[str, object]:
    """grok 图片可用性探测（10 分钟缓存）。"""
    now = time.time()
    if not force and now - float(str(_grok_probe_cache["at"])) < 600:
        return {
            "ok": _grok_probe_cache["ok"],
            "error": _grok_probe_cache["error"],
            "cached": True,
        }
    key = os.environ.get("OPENAI_COMPATIBLE_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=150) as client:
            r = await client.post(
                f"{GROK_ADMIN}/v1/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "grok-imagine-image", "prompt": "a tiny orange dot", "n": 1},
                timeout=150,
            )
            ok = r.status_code == 200
            err = "" if ok else f"HTTP {r.status_code}"
    except Exception as exc:
        ok, err = False, str(exc)[:100]
    _grok_probe_cache.update({"at": now, "ok": ok, "error": err})
    return {"ok": ok, "error": err, "cached": False}


async def _register_status() -> dict[str, object]:
    key = _register_internal_key()
    if not key:
        return {"reachable": False, "error": "未配置注册机内部 key"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{REGISTER_BASE}/api/run/status",
                headers={"x-gra-internal-key": key},
                timeout=10,
            )
            if r.status_code != 200:
                return {"reachable": False, "error": f"HTTP {r.status_code}"}
            d = r.json()
            return {
                "reachable": True,
                "phase": d.get("phase"),
                "current": d.get("current"),
                "total": d.get("total"),
                "success": d.get("success"),
                "failed": d.get("failed"),
                "error": d.get("errorMessage") or "",
            }
    except Exception as exc:
        return {"reachable": False, "error": str(exc)[:120]}


async def _cpa_status(db: AsyncSession) -> dict[str, object]:
    """cpa 探活（带 DB 里的解密 key）。"""
    from sqlalchemy import select

    from app.models.provider_config import ProviderConfig
    from app.security.ownership import open_secret

    key = ""
    try:
        row = (
            await db.execute(
                select(ProviderConfig).where(ProviderConfig.name.contains("cpa"))
            )
        ).scalar_one_or_none()
        if row and row.encrypted_api_key:
            key = open_secret(row.encrypted_api_key)
    except Exception as exc:
        logger.warning("cpa_probe_key_failed", error=str(exc)[:150])
    try:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{CPA_BASE}/v1/models", headers=headers, timeout=8)
            ok = r.status_code == 200
            return {"reachable": ok, "error": "" if ok else f"HTTP {r.status_code}"}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)[:100]}


@router.get("/status")
async def upstream_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    pool = await _grok_account_pool()
    reg = await _register_status()
    grok_img = await _grok_image_probe()
    cpa = await _cpa_status(db)
    return {"grok_pool": pool, "register": reg, "grok_image": grok_img, "cpa": cpa}


@router.post("/register", response_model=TaskResponse)
async def trigger_registration(
    run_count: int = Query(10, ge=1, le=MAX_REGISTER_RUN_COUNT),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskResponse:
    """触发注册机跑一批注册（记录为 register 任务，进程内后台执行）。

    admin-only；数量受 MAX_REGISTER_RUN_COUNT 限制；
    已有 queued/processing 的批次时拒绝（防 beat + 手动并发叠批次）。
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可触发注册批次")
    running = (
        await db.execute(
            select(GenerationTask.id).where(
                GenerationTask.task_type == "register",
                GenerationTask.status.in_(["queued", "processing"]),
            )
        )
    ).first()
    if running is not None:
        raise HTTPException(status_code=409, detail="已有注册批次进行中，请等待完成")
    from app.tasks.register_batch import schedule_register_batch

    task = GenerationTask(
        task_type="register",
        status="queued",
        model="grok-register",
        params=json.dumps({"run_count": run_count}),
        user_id=user.id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    schedule_register_batch(task.id, run_count)
    return TaskResponse.model_validate(task)


@router.get("/register/result/{task_id}")
async def register_result(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    task = (
        await db.execute(
            select(GenerationTask).where(
                GenerationTask.id == task_id, GenerationTask.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if task is None and user.role != "admin":
        return {"status": "not_found"}
    if task is None:
        task = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
    if task is None:
        return {"status": "not_found"}
    return {
        "id": task.id,
        "status": task.status,
        "result": json.loads(task.result or "{}"),
        "error_message": task.error_message,
        "created_at": str(task.created_at),
    }
