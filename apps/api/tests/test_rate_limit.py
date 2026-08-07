"""限流与登录保护。"""

from __future__ import annotations

from app.core.config import settings
from app.core.rate_limit import _hits


async def test_login_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_MINUTE", 3)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 0)
    _hits.clear()

    codes = []
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "nope", "password": "wrong"},
        )
        codes.append(resp.status_code)

    assert 429 in codes
    # 前几次应为 401（凭证错误），触发限流后 429
    assert codes.count(401) >= 1
    _hits.clear()
