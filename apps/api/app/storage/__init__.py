"""Storage 包（P0-4 薄 facade）。

P0-4 后：实际实现已迁到 `app.core.runtime.storage.*`。
本包**只**保留 wrapper 以兼容现有 import 路径（路由层 / 老代码
`from app.storage import get_storage`）。

迁移后保留符号：
- get_storage, choose_write_backend, normalize_backend, reset_storage_cache
- ObjectStorage, BaseStorage（来自 app.storage.base → core.runtime.storage.base）

P 阶段清理时评估是否彻底移除此包。
"""
from app.core.runtime.storage import ObjectStorage  # noqa: F401  # 兼容
from app.core.runtime.storage import BaseStorage  # noqa: F401  # 兼容
from app.core.runtime.storage.base import (  # noqa: F401
    ObjectStorage as _ObjectStorage,
    BaseStorage as _BaseStorage,
)
from app.core.runtime.storage.registry import (  # noqa: F401
    _VALID_BACKENDS,
    choose_write_backend,
    get_storage,
    normalize_backend,
    reset_storage_cache,
)

# 同时导出 BaseStorage / ObjectStorage 顶层名（兼容 app.storage.base 旧导入）
ObjectStorage = _ObjectStorage
BaseStorage = _BaseStorage
__all__ = [
    "BaseStorage",
    "ObjectStorage",
    "choose_write_backend",
    "get_storage",
    "normalize_backend",
    "reset_storage_cache",
]
