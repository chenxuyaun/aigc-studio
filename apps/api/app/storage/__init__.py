from __future__ import annotations

import hashlib
from functools import lru_cache

from app.core.config import settings
from app.storage.base import ObjectStorage
from app.storage.local_provider import LocalStorageProvider

_VALID_BACKENDS = frozenset({"local", "r2", "s3", "b2", "minio"})


def normalize_backend(name: str | None) -> str:
    raw = (name or "local").strip().lower()
    if raw not in _VALID_BACKENDS:
        raise ValueError(f"不支持的存储 backend: {raw!r}，可选: {sorted(_VALID_BACKENDS)}")
    return raw


def choose_write_backend(user_id: str) -> str:
    """按用户稳定哈希灰度写入 R2；percent<=0 时全部 local。"""
    percent = int(getattr(settings, "STORAGE_R2_WRITE_PERCENT", 0) or 0)
    if percent <= 0:
        return "local"
    if percent >= 100:
        # 仍需 R2 配置完整，否则 fail-fast
        _ = get_storage("r2")
        return "r2"
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if bucket < percent:
        _ = get_storage("r2")
        return "r2"
    return "local"


@lru_cache(maxsize=8)
def get_storage(backend: str | None = None) -> ObjectStorage:
    """按 backend 返回存储驱动。

    - 无参或 backend=None：使用 settings.STORAGE_PROVIDER 作为默认（兼容旧调用）
    - 显式 backend：按行上的 storage_backend 读取/删除
    """
    name = normalize_backend(backend if backend is not None else settings.STORAGE_PROVIDER)

    if name == "local":
        return LocalStorageProvider(base_path=settings.STORAGE_LOCAL_PATH)

    # s3 兼容族
    if name in {"s3", "r2", "b2", "minio"}:
        from app.storage.s3_provider import S3CompatibleStorageProvider

        # 用户媒体：禁止 public base（封面公共桶不走此工厂写路径）
        return S3CompatibleStorageProvider(
            endpoint=settings.STORAGE_ENDPOINT,
            access_key=settings.STORAGE_ACCESS_KEY,
            secret_key=settings.STORAGE_SECRET_KEY,
            bucket=settings.STORAGE_BUCKET,
            region=settings.STORAGE_REGION or "auto",
            public_base_url="",  # 强制空
            backend="r2" if name == "r2" else name,
            allow_public_base_url=False,
        )

    raise ValueError(f"不支持的存储 backend: {name}")


def reset_storage_cache() -> None:
    """测试或热更新配置时清空单例。"""
    get_storage.cache_clear()
