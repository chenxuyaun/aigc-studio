"""AgentList 目录定时同步任务（beat 每周执行，管理员也可手动触发）。"""

from __future__ import annotations

import asyncio

from app.tasks.celery_app import celery_app
from app.tasks.generation_tasks import _RETRYABLE


@celery_app.task(  # type: ignore[untyped-decorator]
    name="agentlist_sync_task",
    max_retries=2,
    autoretry_for=_RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def agentlist_sync_task() -> dict[str, object]:
    """下载 llms-full.txt 并幂等入库（与手动 sync 同一路径）。"""

    async def _run() -> dict[str, object]:
        from app.core.database import AsyncSessionLocal, engine
        from app.services.agentlist_ingest import sync_agentlist

        # celery prefork + asyncio.run：dispose 连接池避免跨 loop 连接卡死
        await engine.dispose()
        async with AsyncSessionLocal() as db:
            try:
                counts = await sync_agentlist(db)
            except Exception as e:
                if isinstance(e, _RETRYABLE):
                    raise  # DB 抖动自动重试
                return {"ok": False, "error": str(e)[:300]}
            return {"ok": True, **counts}

    return asyncio.run(_run())
