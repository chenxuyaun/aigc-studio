"""resolve_text_provider 语义：空 model 自动选最优真实 provider，无可用时抛错。"""

from __future__ import annotations

import pytest
from app.services.provider_resolver import NoTextProviderError, resolve_text_provider


@pytest.mark.asyncio
async def test_empty_model_resolves_to_real_provider(client, admin_token) -> None:
    """空 model（前端「自动/默认」）必须解析到真实 provider，而不是 mock。"""
    from app.models.provider_config import ProviderConfig
    from app.security.ownership import seal_secret

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        db.add(
            ProviderConfig(
                name="TestLLM",
                provider_type="openai_compatible",
                base_url="http://127.0.0.1:8000/v1",
                default_model="test-llm",
                is_enabled=True,
                priority=0,
                encrypted_api_key=seal_secret("test-key"),
            )
        )
        await db.commit()

        r = await resolve_text_provider(db, "")
        assert r.is_real is True
        assert r.model == "test-llm"
        assert r.source == "db"
        assert r.provider_config_id is not None

        # 空字符串 / None 等价
        r2 = await resolve_text_provider(db, None)  # type: ignore[arg-type]
        assert r2.is_real is True

        # 显式 "mock" 不再返回离线假数据：解析为真实 provider 或报错，绝不 is_real=False
        r3 = await resolve_text_provider(db, "mock")
        assert r3.is_real is True


@pytest.mark.asyncio
async def test_explicit_id_matches_provider(client, admin_token) -> None:
    """按 ProviderConfig.id 精确匹配。"""
    from app.models.provider_config import ProviderConfig
    from app.security.ownership import seal_secret

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        cfg = ProviderConfig(
            name="Named",
            provider_type="openai_compatible",
            base_url="http://127.0.0.1:8000/v1",
            default_model="named-model",
            is_enabled=True,
            priority=5,
            encrypted_api_key=seal_secret("k"),
        )
        db.add(cfg)
        await db.commit()

        r = await resolve_text_provider(db, cfg.id)
        assert r.is_real is True
        assert r.model == "named-model"
        assert r.provider_config_id == cfg.id


@pytest.mark.asyncio
async def test_disabled_provider_skipped(client, admin_token) -> None:
    """禁用配置不参与解析。"""
    from app.models.provider_config import ProviderConfig
    from app.security.ownership import seal_secret

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        db.add(
            ProviderConfig(
                name="DisabledLLM",
                provider_type="openai_compatible",
                base_url="http://127.0.0.1:8000/v1",
                default_model="disabled-model",
                is_enabled=False,
                priority=0,
                encrypted_api_key=seal_secret("k"),
            )
        )
        await db.commit()

        # 禁用配置被跳过：解析到 env 兜底或抛 NoTextProviderError，绝不是被禁用的那个
        try:
            r = await resolve_text_provider(db, "disabled-model")
        except NoTextProviderError:
            return  # 无 env 兜底：符合「无可用 provider 抛错」语义
        assert r.is_real is True
        assert r.source == "env"  # 禁用配置不参与；真实 env 兜底（而非离线 mock）
