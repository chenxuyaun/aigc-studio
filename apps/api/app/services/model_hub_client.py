"""模型中心客户端（P0-5 薄 facade）。

P0-5 后：实际实现已迁到 `app.core.runtime.model.router`。
本模块**只**保留 wrapper 以兼容现有 import 路径（路由层 / 老代码
`from app.services.model_hub_client import get_active_chain, ...`）。

P 阶段清理时如无外部依赖可彻底删除此 facade。
"""
from app.core.runtime.model.router import (  # noqa: F401  # 兼容
    get_active_chain,
    get_active_config,
    list_providers,
)

__all__ = ["get_active_chain", "get_active_config", "list_providers"]
