"""Core Runtime - Model Hub 客户端（Router 抽象）。

P0-5 抽离：从 services/model_hub_client.py 整体搬过来。
- router.py:   get_active_chain / get_active_config / list_providers
- resolver.py: ResolvedTextProvider + list_enabled_text_catalog + resolve_text_provider

P0 边界：app.services.model_hub_client + app.services.provider_resolver 保留 facade，
新代码用 core.runtime.model.*。
"""
from app.core.runtime.model.resolver import (  # noqa: F401  # 兼容
    NoTextProviderError,
    ResolvedTextProvider,
    list_enabled_text_catalog,
    resolve_text_provider,
)
from app.core.runtime.model.router import (  # noqa: F401  # 兼容
    get_active_chain,
    get_active_config,
    list_providers,
)

__all__ = [
    "NoTextProviderError",
    "ResolvedTextProvider",
    "get_active_chain",
    "get_active_config",
    "list_enabled_text_catalog",
    "list_providers",
    "resolve_text_provider",
]
