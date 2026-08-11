"""ASMR 聚合同步任务（beat 每日增量，管理员可手动触发全量）。"""

from __future__ import annotations

import asyncio

from app.tasks.celery_app import celery_app
from app.tasks.generation_tasks import _RETRYABLE


@celery_app.task(  # type: ignore[untyped-decorator]
    name="asmr_sync_task",
    time_limit=2700,
    soft_time_limit=2580,
    max_retries=2,
    autoretry_for=_RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def asmr_sync_task(
    mode: str = "daily",
    keyword: str = "",
    update_existing: bool = False,
    start_page: int = 1,
) -> dict[str, object]:
    """拉取 asmr.one 元数据并幂等入库（与手动 sync 同一路径）。

    全量约 13 分钟（1248 页 × 0.6s 限速），覆盖全局 600s 上限。
    update_existing=True：已有作品也刷新封面/标签/评分（修复历史解析问题）。
    start_page>1：断点续跑（限时中断后从指定页继续）。
    """

    async def _run() -> dict[str, object]:
        from app.core.cache import cache_clear_prefix
        from app.core.database import AsyncSessionLocal, engine
        from app.services.asmr_ingest import run_sync

        # celery prefork + asyncio.run：dispose 连接池避免跨 loop 连接卡死
        await engine.dispose()
        # 跨进程互斥：beat 每日同步与手动 /asmr/sync（进程内锁互不共享）防双跑浪费限速配额
        from app.core.cache import redis_lock

        if not await redis_lock("aigc:lock:asmr_sync", ttl=2700):
            return {"ok": False, "error": "已有 ASMR 同步运行中，本次跳过"}
        async with AsyncSessionLocal() as db:
            try:
                result = await run_sync(
                    db,
                    mode=mode,
                    keyword=keyword,
                    update_existing=update_existing,
                    start_page=start_page,
                )
            except Exception as e:
                if isinstance(e, _RETRYABLE):
                    raise  # DB 抖动自动重试
                return {"ok": False, "mode": mode, "error": str(e)[:300]}
            # 入库后使列表查询缓存失效
            await cache_clear_prefix("asmr:works:")
            return {"ok": True, **result}

    return asyncio.run(_run())
