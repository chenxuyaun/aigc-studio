"""进程内滑动窗口限流（单实例足够；多实例请换 Redis）。

安全策略（审计 S5 修复）：
- 默认不信任客户端 X-Forwarded-For（可伪造绕过），直连场景取 socket IP。
- 仅当 TRUST_PROXY=true（nginx 等受信代理之后）才取 XFF 首值；
  受信代理应覆盖/剥离客户端自造的 XFF。
- _hits 惰性清理：空队列移除 + 定期全清，避免内存无界增长。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.core.config import settings
from fastapi import HTTPException, Request

_hits: dict[str, deque[float]] = defaultdict(deque)
_last_sweep = time.monotonic()
_SWEEP_INTERVAL = 600.0  # 每 10 分钟全清一次窗口


def _client_ip(request: Request) -> str:
    if settings.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host
    return "unknown"


def _sweep(now: float) -> None:
    """清理空 key 与过期窗口，防止字典无界增长。"""
    global _last_sweep
    if now - _last_sweep < _SWEEP_INTERVAL:
        return
    _last_sweep = now
    expired = [k for k, q in _hits.items() if not q or now - q[-1] > 60.0]
    for k in expired:
        _hits.pop(k, None)


def check_rate_limit(request: Request, *, limit: int | None = None, bucket: str = "global") -> None:
    max_per_min = limit if limit is not None else int(settings.RATE_LIMIT_PER_MINUTE or 0)
    if max_per_min <= 0:
        return

    now = time.monotonic()
    _sweep(now)

    key = f"{bucket}:{_client_ip(request)}"
    window = 60.0
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if not q:
        _hits.pop(key, None)  # 空窗口不占内存
        q = _hits[key]
    if len(q) >= max_per_min:
        # 告知窗口最早一条还要多久滑出，避免前端统一傻等 60s。
        oldest = q[0] if q else now
        retry_after = max(1, int(window - (now - oldest)) + 1)
        raise HTTPException(
            status_code=429,
            detail="请求过于频繁，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )
    q.append(now)
