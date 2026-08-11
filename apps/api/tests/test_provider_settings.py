"""DB ProviderConfig 解析（task_runner 真实链路配置来源）。"""

from __future__ import annotations

import pytest
from app.services.task_runner import _provider_settings


@pytest.mark.asyncio
async def test_provider_settings_by_alias_name(client, admin_token):
    """别名（grok）能大小写不敏感匹配到 DB 配置名「Grok（本地 grok2api）」。"""
    from app.models.provider_config import ProviderConfig
    from app.security.ownership import seal_secret

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        db.add(
            ProviderConfig(
                name="Grok（本地 grok2api）",
                provider_type="openai_compatible",
                base_url="http://127.0.0.1:8000/v1",
                default_model="grok-chat-fast",
                is_enabled=True,
                priority=1,
                encrypted_api_key=seal_secret("test-key"),
            )
        )
        await db.commit()

        base_url, api_key, default_model = (await _provider_settings(db, "grok")) or ("", "", "")
        assert base_url == "http://127.0.0.1:8000/v1"
        assert api_key == "test-key"
        assert default_model == "grok-chat-fast"

        # 未注册的模型 → None（走 env 兜底）
        assert await _provider_settings(db, "no-such-provider") is None
