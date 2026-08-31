"""Core Runtime - 文本 Provider 解析（P2 收敛版）。

从 services/provider_resolver.py 抽离：
- ResolvedTextProvider: 解析结果 dataclass
- list_enabled_text_catalog: 前端模型下拉目录（hub + env 兜底）
- resolve_text_provider: 实际解析（hub text 候选链优先 → env 兜底）
- NoTextProviderError: 不可用错误

P0 边界：app.services.provider_resolver 保留 facade，业务层 import 仍可用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.runtime.model.router import get_active_chain, get_active_config, list_providers
from app.providers.openai_compatible import OpenAICompatibleTextProvider


class NoTextProviderError(RuntimeError):
    """没有可用的文本 Provider（系统未配置任何真实模型）。"""


@dataclass
class ResolvedTextProvider:
    provider: object
    model: str
    is_real: bool
    provider_config_id: str | None = None  # P3 随 provider_configs 表一起移除
    source: str = "env"  # hub | env


async def list_enabled_text_catalog(db: AsyncSession) -> list[dict[str, object]]:
    """前端模型下拉目录：模型中心 text 能力供应商；hub 不可用时 env 兜底条目。

    db 参数保留以兼容调用方签名（P2 起不再查 DB）。
    """
    items: list[dict[str, object]] = []
    try:
        for p in await list_providers():
            if not p.get("is_enabled", True):
                continue
            caps = p.get("capabilities") or {}
            if isinstance(caps, str):
                import json as _json

                try:
                    caps = _json.loads(caps)
                except Exception:  # noqa: BLE001
                    caps = {}
            if isinstance(caps, dict) and not caps.get("text"):
                continue
            items.append(
                {
                    "id": str(p.get("id") or ""),
                    "name": str(p.get("name") or ""),
                    "provider_type": str(p.get("provider_type") or "openai_compatible"),
                    "default_model": str(p.get("default_model") or p.get("name") or ""),
                    "is_enabled": True,
                    "source": "hub",
                }
            )
    except Exception:  # noqa: BLE001 - 模型中心不可用时静默走 env 条目
        items = []

    # 环境变量兜底条目（库中尚无同 base 时展示）
    if settings.OPENAI_COMPATIBLE_BASE_URL and settings.OPENAI_COMPATIBLE_MODEL:
        env_model = settings.OPENAI_COMPATIBLE_MODEL
        if not any(i.get("default_model") == env_model for i in items):
            items.append(
                {
                    "id": "env-openai",
                    "name": f"环境变量 · {env_model}",
                    "provider_type": "openai_compatible",
                    "default_model": env_model,
                    "is_enabled": True,
                    "source": "env",
                }
            )
    return items


async def resolve_text_provider(db: AsyncSession, requested_model: str) -> ResolvedTextProvider:
    """解析文本 Provider。

    0) 模型中心 text 槽位候选链优先（v3 故障转移，主选在前）；
       空 model 表示「自动」= 用链首 default_model。
    1) env `OPENAI_COMPATIBLE_*` 兜底。
    系统无任何可用 Provider 时抛 NoTextProviderError（不产出离线假数据）。
    """
    requested = (requested_model or "").strip()
    _ = requested  # 显式 model 名不再跨供应商传递：链首 default_model 优先

    # 0) 模型中心 text 候选链
    try:
        from app.providers.failover import FailoverTextProvider

        chain = await get_active_chain("text")
        confs = [c for c in chain if (c.get("base_url") or "").strip()]
        if confs:
            providers = [
                OpenAICompatibleTextProvider(
                    base_url=c["base_url"],
                    api_key=c.get("api_key") or "none",
                    default_model=c.get("default_model") or "",
                    timeout=180,
                )
                for c in confs
            ]
            model_name = confs[0].get("default_model") or ""
            provider: Any = providers[0]
            if len(providers) > 1:
                provider = FailoverTextProvider(providers)
            return ResolvedTextProvider(provider, model_name, True, source="hub")
    except NoTextProviderError:
        raise
    except Exception:  # noqa: BLE001 - 模型中心不可用 → env 兜底
        pass

    # 1) 环境变量兜底
    if settings.OPENAI_COMPATIBLE_BASE_URL:
        use_model = (
            requested
            if requested and requested != "env-openai"
            else (settings.OPENAI_COMPATIBLE_MODEL or "grok-4.5")
        )
        return ResolvedTextProvider(
            OpenAICompatibleTextProvider(
                base_url=settings.OPENAI_COMPATIBLE_BASE_URL,
                api_key=settings.OPENAI_COMPATIBLE_API_KEY or "none",
                default_model=settings.OPENAI_COMPATIBLE_MODEL or use_model,
                timeout=180,
            ),
            use_model,
            True,
            source="env",
        )

    raise NoTextProviderError(
        "未配置可用的文本模型：请在模型中心（服务器 :8511）设置 text 槽位，或配置 OPENAI_COMPATIBLE_* 环境变量"
    )
