"""文本 Provider 解析（P0-5 薄 facade）。

P0-5 后：实际实现已迁到 `app.core.runtime.model.resolver`。
本模块**只**保留 wrapper 以兼容现有 import 路径（业务层 / 老代码
`from app.services.provider_resolver import resolve_text_provider, ...`）。

P 阶段清理时如无外部依赖可彻底删除此 facade。
"""
from app.core.runtime.model.resolver import (  # noqa: F401  # 兼容
    NoTextProviderError,
    ResolvedTextProvider,
    list_enabled_text_catalog,
    resolve_text_provider,
)

__all__ = ["NoTextProviderError", "ResolvedTextProvider", "list_enabled_text_catalog", "resolve_text_provider"]
