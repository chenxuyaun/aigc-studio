import os
from pathlib import Path

import aiofiles

from app.storage.base import ObjectStorage


class LocalStorageProvider(ObjectStorage):
    """本地文件对象存储（开发/单机默认）。生产环境改用 S3 兼容驱动。"""

    backend = "local"

    def __init__(self, base_path: str = "./storage") -> None:
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    def _path(self, key: str) -> str:
        # 防止路径穿越：规范化后必须仍位于 base_path 之内。
        root = Path(self.base_path).resolve()
        full = (root / key).resolve()
        if not full.is_relative_to(root):
            raise ValueError("非法的存储 key")
        return str(full)

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
        return key

    async def get(self, key: str) -> bytes:
        async with aiofiles.open(self._path(key), "rb") as f:
            return await f.read()

    async def delete(self, key: str) -> bool:
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    async def get_url(self, key: str) -> str:
        # local 不提供公网直链；业务层应走鉴权 content / access-url。
        return f"/storage/{key}"

    async def signed_get_url(self, key: str, expires_seconds: int = 300) -> str:
        del expires_seconds  # local 无签名；由 API 层映射到受鉴权 content 路径
        return await self.get_url(key)
