"""注册批次任务：调注册机 API 跑一批注册，更新 generation_tasks(register) 结果。

触发源：
- 前端「上游状态」页手动触发（POST /api/v1/upstream/register → 进程内后台执行）
- celery beat 定时（见 celery_app.beat_schedule）—— 自动创建任务记录后执行

执行：调注册机 /api/run/start → 轮询 /api/run/status 至 idle → 写任务结果。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid

import httpx
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.generation_task import GenerationTask
from app.tasks.celery_app import celery_app

REGISTER_BASE = os.environ.get("REGISTER_BASE", "http://host.docker.internal:6657")
POLL_INTERVAL = 30
MAX_WAIT = 4 * 3600  # 单批最长 4 小时


def _internal_key() -> str:
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


STALL_SECONDS = 25 * 60  # run 挂起判定：成功+失败计数 25 分钟无变化


def _headers(key: str) -> dict[str, str]:
    # 注册机同时接受两个 header 名，兼容不同版本
    return {"x-gra-internal-key": key, "X-Internal-Key": key}


async def _start(client: httpx.AsyncClient, key: str, run_count: int) -> dict[str, object]:
    r = await client.post(
        f"{REGISTER_BASE}/api/run/start",
        headers=_headers(key),
        json={"runCount": run_count, "run_count": run_count},
        timeout=30,
    )
    if r.status_code != 200:
        return {"ok": False, "error": f"start HTTP {r.status_code}: {r.text[:120]}"}
    return {"ok": True}


async def _run_batch(run_count: int) -> dict[str, object]:
    """多轮执行：start → 轮询 → 完成/挂起（stop+重启剩余）→ 写最终结果。

    注册机 run 偶发挂起（浏览器标签卡死，进程存活但无进展），
    之前曾卡 8 小时 —— 这里对「计数 25 分钟无变化」的 run 自动
    stop 后重启剩余数量，直到累计完成目标或 4h 超时。

    注意：status 的 success/failed 是当前 run 的计数，跨 run 不累计；
    本函数维护 acc（run 结束/挂起停止时并入该 run 计数）。
    """
    key = _internal_key()
    if not key:
        return {"ok": False, "error": "未配置注册机内部 key"}
    # 跨进程互斥：beat 12h + 手动触发防叠批次（锁 4h TTL，不手动释放）
    from app.core.cache import redis_lock

    if not await redis_lock("aigc:lock:register_batch", ttl=4 * 3600):
        return {"ok": False, "error": "已有注册批次运行中，本次跳过"}
    acc = 0  # 跨 run 累计 success+failed
    current_rid: str | None = None
    restart_count = 0
    async with httpx.AsyncClient(timeout=30) as client:
        deadline = time.time() + MAX_WAIT
        while time.time() < deadline:
            # 阶段 1：确保有 run 在跑
            if current_rid is None:
                remain = run_count - acc
                if remain <= 0:
                    return {
                        "ok": True,
                        "phase": "done",
                        "success": acc,
                        "failed": 0,
                        "total": run_count,
                        "restart_count": restart_count,
                        "error": "",
                    }
                r = await _start(client, key, remain)
                if not r.get("ok"):
                    return r
                # 等 status 出现 runId
                for _ in range(6):
                    await asyncio.sleep(5)
                    try:
                        s = await client.get(
                            f"{REGISTER_BASE}/api/run/status",
                            headers=_headers(key),
                            timeout=30,
                        )
                    except Exception:
                        continue
                    if s.status_code == 200 and s.json().get("runId"):
                        current_rid = s.json()["runId"]
                        break
                if current_rid is None:
                    continue
                stall_since = time.time()
                last_count = (s.json().get("success") or 0) + (s.json().get("failed") or 0)
                continue
            # 阶段 2：轮询当前 run 直到结束或挂起
            await asyncio.sleep(POLL_INTERVAL)
            try:
                s = await client.get(
                    f"{REGISTER_BASE}/api/run/status",
                    headers=_headers(key),
                    timeout=30,
                )
            except Exception:
                continue
            if s.status_code != 200:
                continue
            st = s.json()
            phase = st.get("phase") or ""
            rid = st.get("runId")
            count = (st.get("success") or 0) + (st.get("failed") or 0)
            if rid and rid != current_rid:
                current_rid = rid
                stall_since = time.time()
                last_count = count
                continue
            if count != last_count:
                last_count = count
                stall_since = time.time()
            if phase in ("idle", "done", "stopped", "killed", "failed", "error"):
                acc += count
                current_rid = None
                if acc >= run_count:
                    # 正常完成（阶段 1 也会在 remain<=0 时返回，这里兜底）
                    return {
                        "ok": True,
                        "phase": phase,
                        "success": acc,
                        "failed": 0,
                        "total": run_count,
                        "restart_count": restart_count,
                        "error": "",
                    }
                restart_count += 1  # 未完成即重启（异常终止/提前退出）
                continue
            # 挂起：run 活着但 25 分钟无进展
            if phase == "running" and time.time() - stall_since > STALL_SECONDS:
                with contextlib.suppress(Exception):
                    await client.post(
                        f"{REGISTER_BASE}/api/run/stop",
                        headers=_headers(key),
                        timeout=30,
                    )
                acc += count  # 挂起 run 已完成的账号并入累计
                current_rid = None
                restart_count += 1
                await asyncio.sleep(5)
        return {"ok": False, "error": "批次超时（4h）"}


async def _update_task(task_id: str, result: dict[str, object]) -> None:
    async with AsyncSessionLocal() as db:
        task = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
        if task is None:
            return
        task.status = "succeeded" if result.get("ok") else "failed"
        task.result = json.dumps(result, ensure_ascii=False)
        if not result.get("ok"):
            task.error_message = str(result.get("error") or "注册批次失败")[:400]
        await db.commit()


async def _execute_and_update(task_id: str, run_count: int) -> dict[str, object]:
    # celery prefork + asyncio.run：dispose 连接池避免跨 loop 连接卡死
    from app.core.database import engine

    await engine.dispose()
    result = await _run_batch(run_count)
    await _update_task(task_id, result)
    return result


def schedule_register_batch(task_id: str, run_count: int = 10) -> None:
    """进程内后台执行（不依赖 celery worker）。"""
    import asyncio

    loop = asyncio.get_event_loop()

    async def _runner() -> None:
        await _execute_and_update(task_id, run_count)

    try:
        scheduled = loop.create_task(_runner())
        # 持有引用防止 GC；任务内部自行更新 DB，无需等待
        assert scheduled is not None
    except RuntimeError:
        # 无运行中 loop（如 CLI 场景）：新开 loop 跑完即退
        asyncio.run(_execute_and_update(task_id, run_count))


@celery_app.task(name="register_batch")  # type: ignore[untyped-decorator]
def register_batch(task_id: str = "", run_count: int = 10) -> dict[str, object]:
    """Celery 定时入口：自动创建任务记录后执行注册批次。"""
    if not task_id:
        task_id = _create_task_record(run_count)
    return asyncio.run(_execute_and_update(task_id, run_count))


def _create_task_record(run_count: int) -> str:
    async def _create() -> str:
        async with AsyncSessionLocal() as db:
            # 系统任务归属 admin：generation_tasks.user_id 有 FK（→users.id），
            # 空串会违反外键导致批次永远建不了（MySQL 1452）
            from app.models.user import User

            admin = (
                await db.execute(select(User).where(User.role == "admin").limit(1))
            ).scalar_one_or_none()
            uid = str(admin.id) if admin else ""
            task = GenerationTask(
                id=str(uuid.uuid4()),
                task_type="register",
                status="queued",
                model="grok-register",
                params=json.dumps({"run_count": run_count}),
                user_id=uid,  # 定时任务归属 admin（FK 约束要求有效用户）
            )
            db.add(task)
            await db.commit()
            return task.id

    return asyncio.run(_create())
