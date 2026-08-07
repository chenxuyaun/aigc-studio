"""从 DB / 环境变量解析文本 Provider。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.provider_config import ProviderConfig
from app.providers.openai_compatible import OpenAICompatibleTextProvider
from app.security.ownership import open_secret


class NoTextProviderError(RuntimeError):
    """没有可用的文本 Provider（系统未配置任何真实模型）。"""


@dataclass
class ResolvedTextProvider:
    provider: object
    model: str
    is_real: bool
    provider_config_id: str | None = None
    source: str = "db"  # db | env


async def list_enabled_text_catalog(db: AsyncSession) -> list[dict[str, object]]:
    """前端模型下拉：启用的 text/openai 兼容配置（不含 mock）。"""
    rows = (
        await db.execute(
            select(ProviderConfig)
            .where(
                ProviderConfig.is_enabled.is_(True),
                or_(
                    ProviderConfig.provider_type.in_(
                        ["text", "openai_compatible", "openai", "chat", "llm"]
                    ),
                    ProviderConfig.provider_type == "",
                ),
            )
            .order_by(ProviderConfig.priority.asc(), ProviderConfig.created_at.asc())
        )
    ).scalars().all()
    items: list[dict[str, object]] = []
    for p in rows:
        if not (p.base_url or "").strip() and not (p.default_model or "").strip():
            continue
        items.append(
            {
                "id": p.id,
                "name": p.name,
                "provider_type": p.provider_type,
                "default_model": p.default_model or p.name,
                "is_enabled": True,
                "source": "db",
            }
        )
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


async def resolve_text_provider(
    db: AsyncSession, requested_model: str
) -> ResolvedTextProvider:
    """解析文本 Provider。

    空 model 表示「自动」：选择优先级最高的启用真实 Provider（DB 优先、env 兜底）。
    系统无任何可用 Provider 时抛 NoTextProviderError（不产出离线假数据）。
    """
    requested = (requested_model or "").strip()

    # 1) 按 id 精确匹配
    if requested:
        by_id = (
            await db.execute(select(ProviderConfig).where(ProviderConfig.id == requested))
        ).scalar_one_or_none()
        if by_id and by_id.is_enabled and (by_id.base_url or "").strip():
            return _from_row(by_id, model_override=by_id.default_model or requested)

    rows = (
        await db.execute(
            select(ProviderConfig)
            .where(ProviderConfig.is_enabled.is_(True))
            .order_by(ProviderConfig.priority.asc(), ProviderConfig.created_at.asc())
        )
    ).scalars().all()

    # 2) 按 default_model / name 匹配启用配置
    if requested:
        for p in rows:
            if not (p.base_url or "").strip():
                continue
            if p.default_model == requested or p.name == requested:
                return _from_row(p, model_override=requested)

    # 3) 任意启用的 text 类：显式请求时用请求 model 名打上游；自动时取最优配置
    for p in rows:
        if not (p.base_url or "").strip():
            continue
        if p.provider_type in ("text", "openai_compatible", "openai", "chat", "llm", ""):
            return _from_row(p, model_override=requested or p.default_model or p.name)

    # 4) 环境变量
    if settings.OPENAI_COMPATIBLE_BASE_URL:
        if requested and requested != "env-openai":
            use_model = requested
        else:
            use_model = settings.OPENAI_COMPATIBLE_MODEL or "grok-4.5"
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

    raise NoTextProviderError("未配置可用的文本模型，请在「模型配置」中启用一个 Provider")


def _from_row(p: ProviderConfig, *, model_override: str) -> ResolvedTextProvider:
    key = open_secret(p.encrypted_api_key or "") or "none"
    actual = model_override or p.default_model or "default"
    # grok2api 等网关首 token 可能很慢，超时下限 120s
    timeout = max(int(p.timeout_seconds or 60), 120)
    return ResolvedTextProvider(
        OpenAICompatibleTextProvider(
            base_url=p.base_url,
            api_key=key,
            default_model=p.default_model or actual,
            timeout=timeout,
        ),
        actual,
        True,
        provider_config_id=p.id,
        source="db",
    )
