from abc import ABC, abstractmethod


class ObjectStorage(ABC):
    """对象存储抽象。backend 标识实现（local / r2 / s3 / ...）。"""

    backend: str = "local"

    @abstractmethod
    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> bool: ...

    @abstractmethod
    async def get_url(self, key: str) -> str:
        """兼容旧接口：公开/内部定位用，不用于私有媒体最终交付。"""
        ...

    async def signed_get_url(self, key: str, expires_seconds: int = 300) -> str:
        """短时可读 URL。local 默认回退 get_url；S3/R2 必须覆盖为预签名。"""
        return await self.get_url(key)
