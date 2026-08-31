"""Core Runtime - Storage 抽象层。

P0-4 抽离：ObjectStorage 基类 + get_storage 动态选择器 + 已有 local/s3 Provider。

设计目标：
- 抽象接口（BaseStorage）放 Core Runtime
- 已有 Provider（Local/S3）放 Runtime（实现 Core 抽象）
- 未来 Provider（Quark WebDAV / MinIO / OSS / NAS / Google Drive / OneDrive）
  通过 `core.runtime.storage.providers.*` 注册

P0 边界：app.storage.* 保留兼容 wrapper；新代码直接用 core.runtime.storage.*。
"""
from app.core.runtime.storage.base import BaseStorage, ObjectStorage  # noqa: F401

__all__ = ["BaseStorage", "ObjectStorage"]
