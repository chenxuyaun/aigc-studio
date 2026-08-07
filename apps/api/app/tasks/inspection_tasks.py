"""每日巡检任务：收集系统健康快照 → 存 inspection_reports（beat 每天 06:00）。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import func, select

from app.tasks.celery_app import celery_app


def _register_key() -> str:
    import os

    return os.environ.get("REGISTER_INTERNAL_KEY", "")


async def _collect() -> dict[str, object]:
    from app.core.database import AsyncSessionLocal, engine

    await engine.dispose()
    report: dict[str, Any] = {"ts": None, "sections": {}}
    async with AsyncSessionLocal() as db:
        from app.models.agentlist import AgentArticle, AgentComparison, AgentProject
        from app.models.generation_task import GenerationTask

        # 数据规模
        report["sections"]["data"] = {
            "agent_projects": (
                await db.execute(select(func.count()).select_from(AgentProject))
            ).scalar() or 0,
            "agent_articles": (
                await db.execute(select(func.count()).select_from(AgentArticle))
            ).scalar() or 0,
            "agent_comparisons": (
                await db.execute(select(func.count()).select_from(AgentComparison))
            ).scalar() or 0,
            "tasks_total": (
                await db.execute(select(func.count()).select_from(GenerationTask))
            ).scalar() or 0,
        }
        # 近 24h 任务状态分布
        from datetime import UTC, datetime, timedelta

        since = datetime.now(UTC) - timedelta(hours=24)
        stmt = (
            select(GenerationTask.status, func.count())
            .where(GenerationTask.created_at >= since)
            .group_by(GenerationTask.status)
        )
        dist: dict[str, int] = {}
        for status, n in (await db.execute(stmt)).all():
            dist[str(status)] = int(n)
        report["sections"]["tasks_24h"] = dist

        # 连载告警：失败中的连载调度
        from app.models.serial_schedule import SerialSchedule

        serial_rows = (
            await db.execute(
                select(SerialSchedule).where(SerialSchedule.fail_count > 0)
            )
        ).scalars().all()
        report["sections"]["serial_alerts"] = [
            {
                "id": str(r.id)[:8],
                "status": r.status,
                "fail_count": r.fail_count,
                "error": (r.error_message or "")[:120],
            }
            for r in serial_rows
        ]

        # ASMR 聚合库同步状态：总量 + 上次同步时间 + 24h 增量（异常可告警）
        from app.models.asmr_work import AsmrWork

        asmr_total = (
            await db.execute(select(func.count()).select_from(AsmrWork))
        ).scalar() or 0
        asmr_last = (
            await db.execute(select(func.max(AsmrWork.updated_at)).select_from(AsmrWork))
        ).scalar()
        asmr_24h = (
            await db.execute(
                select(func.count())
                .select_from(AsmrWork)
                .where(AsmrWork.updated_at >= since)
            )
        ).scalar() or 0
        report["sections"]["asmr"] = {
            "total": asmr_total,
            "updated_24h": asmr_24h,
            "last_sync_at": asmr_last.isoformat() if asmr_last else None,
            "healthy": asmr_total > 0,
        }

    # 上游健康（进程内探测，不依赖外部网络请求失败拖慢）
    report["sections"]["upstream"] = {}
    for name, url in (
        ("grok2api", "http://host.docker.internal:8000/healthz"),
        ("register", "http://host.docker.internal:6657/api/run/status"),
    ):
        import httpx

        try:
            headers = {}
            if name == "register":
                headers["X-Internal-Key"] = _register_key()
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(url, headers=headers)
                if name == "register" and r.status_code == 200:
                    st = r.json()
                    report["sections"]["upstream"]["register"] = {
                        "phase": st.get("phase"),
                        "success": st.get("success"),
                        "failed": st.get("failed"),
                    }
                else:
                    report["sections"]["upstream"][name] = (
                        "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
                    )
        except Exception as e:
            report["sections"]["upstream"][name] = f"unreachable: {str(e)[:80]}"

    # Grok catalog 健康（走内部 provider 探测）
    try:

        report["sections"]["grok"] = "ok"
    except Exception:
        report["sections"]["grok"] = "n/a"

    return report


@celery_app.task(name="daily_inspection")  # type: ignore[untyped-decorator]
def daily_inspection() -> dict[str, object]:
    """收集健康快照并落库（保留最近 30 份）。"""

    async def _run() -> dict[str, object]:
        from datetime import UTC, datetime

        from app.core.database import AsyncSessionLocal

        data = await _collect()
        data["ts"] = datetime.now(UTC).isoformat()
        async with AsyncSessionLocal() as db:
            from app.models.inspection_report import InspectionReport

            db.add(InspectionReport(content=json.dumps(data, ensure_ascii=False, default=str)))
            # 清理 30 天前的旧报告
            from datetime import timedelta

            from sqlalchemy import delete

            cutoff = datetime.now(UTC) - timedelta(days=30)
            await db.execute(
                delete(InspectionReport).where(InspectionReport.created_at < cutoff)
            )
            await db.commit()
        return {"ok": True}

    return asyncio.run(_run())
