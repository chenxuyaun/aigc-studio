"""S3 兼容对象存储（Cloudflare R2 / Backblaze B2 / MinIO / AWS S3）。

通过 boto3 同步客户端 + asyncio.to_thread 适配异步接口。
用户媒体私有桶禁止配置 public_base_url 作为交付手段；交付一律走预签名 GET。
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app.storage.base import ObjectStorage


class S3CompatibleStorageProvider(ObjectStorage):
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "auto",
        public_base_url: str = "",
        backend: str = "r2",
        allow_public_base_url: bool = False,
    ) -> None:
        if not endpoint or not access_key or not secret_key or not bucket:
            raise ValueError("S3 存储缺少 endpoint / access_key / secret_key / bucket 配置")
        if public_base_url and not allow_public_base_url:
            raise ValueError(
                "用户媒体私有存储禁止 STORAGE_PUBLIC_BASE_URL；请使用预签名 URL 交付"
            )

        self.backend = backend
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")
        self._client: BaseClient = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or "auto",
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(partial(fn, *args, **kwargs))

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        extra: dict[str, str] = {}
        if content_type:
            extra["ContentType"] = content_type
        await self._run(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            **extra,
        )
        return key

    async def get(self, key: str) -> bytes:
        resp = await self._run(self._client.get_object, Bucket=self.bucket, Key=key)
        body = resp["Body"]
        try:
            return await asyncio.to_thread(body.read)
        finally:
            body.close()

    async def delete(self, key: str) -> bool:
        try:
            await self._run(self._client.delete_object, Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    async def get_url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url}/{key.lstrip('/')}"
        return await self.signed_get_url(key, expires_seconds=3600)

    async def signed_get_url(self, key: str, expires_seconds: int = 300) -> str:
        url = await self._run(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=max(30, int(expires_seconds)),
        )
        return str(url)
