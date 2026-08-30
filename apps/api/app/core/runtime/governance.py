"""Core Runtime - Governance 通知。

从 services/task_runner.py 拆出：
- notify_event：统一通知（生成完成/失败 → 通知服务）。失败静默，绝不影响主流程。

P0 边界：task_runner.py 通过 `from app.core.runtime.governance import ...` 使用。
"""
from __future__ import annotations

import os

import httpx

from app.core.config import settings


async def notify_event(event: dict) -> None:
    """统一通知：生成完成/失败 → 通知服务（失败静默，绝不影响主流程）。"""
    url = getattr(settings, "NOTIFY_WEBHOOK_URL", "") or os.environ.get("NOTIFY_WEBHOOK_URL", "")
    if not url or not getattr(settings, "NOTIFY_ENABLED", False):
        return
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(url, json=event)
    except Exception:
        pass
