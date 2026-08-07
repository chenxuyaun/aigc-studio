from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal

router = APIRouter()


async def _check_mysql() -> dict[str, str]:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:300]}


async def _check_redis() -> dict[str, str]:
    url = (settings.REDIS_URL or "").strip()
    if not url:
        return {"status": "skipped", "error": "REDIS_URL empty"}
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(  # type: ignore[no-untyped-call]
            url, socket_connect_timeout=2, socket_timeout=2
        )
        try:
            pong = await client.ping()
            if not pong:
                return {"status": "error", "error": "ping returned falsy"}
            return {"status": "ok"}
        finally:
            await client.aclose()
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:300]}


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    """就绪探针：MySQL 必须可用；Redis 有配置时也检查（失败不阻塞核心 API）。"""
    mysql = await _check_mysql()
    redis = await _check_redis()
    ready_ok = mysql["status"] == "ok"
    if not ready_ok:
        response.status_code = 503
        return {
            "status": "not_ready",
            "mysql": mysql,
            "redis": redis,
            "error": mysql.get("error", "mysql unavailable"),
        }
    return {"status": "ready", "mysql": mysql, "redis": redis}


@router.get("/dependencies")
async def dependencies() -> dict[str, object]:
    # 仅返回健康状态；内部配置（storage provider / r2 灰度 / env）不外泄
    return {
        "dependencies": {
            "mysql": await _check_mysql(),
            "redis": await _check_redis(),
        }
    }
