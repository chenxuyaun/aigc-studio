"""resolve_text_provider 语义（P2 收敛版）：hub 链优先 → env 兜底 → 抛错。

deprecation-plan.md P2：DB provider_configs 通道已下线，不再参与解析。
"""

from __future__ import annotations

import pytest
from app.core.config import settings
from app.services.provider_resolver import NoTextProviderError, resolve_text_provider


def _mock_chain(monkeypatch: pytest.MonkeyPatch, confs: list[dict]) -> None:
    # P0-5 后：实际定义在 core.runtime.model.router。
    # resolve_text_provider 内部 `from .router import get_active_chain` 已经在
    # 加载时绑定到自己命名空间；必须 patch resolver 命名空间里的引用才能生效。
    import app.core.runtime.model.resolver as resolver_mod

    async def fake_chain(slot: str):
        assert slot == "text"
        return confs

    monkeypatch.setattr(resolver_mod, "get_active_chain", fake_chain)


def _env_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OPENAI_COMPATIBLE_BASE_URL", "", raising=False)
    monkeypatch.setattr(settings, "OPENAI_COMPATIBLE_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "OPENAI_COMPATIBLE_MODEL", "", raising=False)


@pytest.mark.asyncio
async def test_hub_chain_wins(client, admin_token, monkeypatch) -> None:
    """模型中心链存在：解析到链首 default_model，source=hub，绝不落 DB/env。"""
    _mock_chain(
        monkeypatch,
        [
            {"base_url": "http://up-a/v1", "api_key": "k1", "default_model": "model-a", "provider_type": "openai_compatible"},
            {"base_url": "http://up-b/v1", "api_key": "k2", "default_model": "model-b", "provider_type": "openai_compatible"},
        ],
    )
    from app.providers.failover import FailoverTextProvider

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        r = await resolve_text_provider(db, "")
        assert r.is_real is True
        assert r.source == "hub"
        assert r.model == "model-a"
        # 多候选 → FailoverTextProvider 包裹
        assert isinstance(r.provider, FailoverTextProvider)

        # 空字符串 / None / 显式名等价：显式 model 不跨供应商传递
        for requested in (None, "whatever-model"):
            r2 = await resolve_text_provider(db, requested)  # type: ignore[arg-type]
            assert r2.source == "hub"


@pytest.mark.asyncio
async def test_env_fallback_when_hub_down(client, admin_token, monkeypatch) -> None:
    """hub 不可用且 env 已配置 → env 兜底。"""
    import app.services.model_hub_client as hub_mod

    async def broken_chain(slot: str):
        raise RuntimeError("hub down")

    monkeypatch.setattr(hub_mod, "get_active_chain", broken_chain)
    monkeypatch.setattr(settings, "OPENAI_COMPATIBLE_BASE_URL", "http://127.0.0.1:8000/v1", raising=False)
    monkeypatch.setattr(settings, "OPENAI_COMPATIBLE_MODEL", "env-model", raising=False)

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        r = await resolve_text_provider(db, "")
        assert r.is_real is True
        assert r.source == "env"
        assert r.model == "env-model"

        # 显式请求非 env-openai 名 → 用请求的 model 名打上游
        r2 = await resolve_text_provider(db, "custom-name")
        assert r2.model == "custom-name"


@pytest.mark.asyncio
async def test_no_provider_raises(client, admin_token, monkeypatch) -> None:
    """hub 不可用 + 无 env → NoTextProviderError（绝不 mock）。"""
    _mock_chain(monkeypatch, [])
    _env_off(monkeypatch)

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        with pytest.raises(NoTextProviderError):
            await resolve_text_provider(db, "")
