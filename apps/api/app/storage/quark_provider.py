"""Storage - Quark WebDAV 对象存储 Provider（P2 新写，计划 §10 必改项）。

把 services/quark_backup.py 的「夸克 WebDAV 备份脚本」能力改写为符合
ObjectStorage 接口的正式 Provider（与 local_provider/s3_provider 同住 app/storage，
registry（core.runtime.storage.registry）按 backend="quark" 分支接入）。

语义：
- key 与其他 provider 同形（如 "user-dir/2026/08/x.png"），
  远端真实路径 = {root_dir}/{key}（逐段 URL 编码，支持中文/空格文件名——旧脚本未编码是缺陷）
- put：先 MKCOL 逐级建父目录（夸克 WebDAV 自动建目录不可靠，沿用旧脚本策略）再 PUT
- get：404 → FileNotFoundError；其余非 2xx → RuntimeError
- delete：2xx → True，404 → False，其余 → RuntimeError
- get_url：内部定位直链（WebDAV 无预签名，signed_get_url 沿用基类回退）

环境变量（与旧脚本同名，.env 契约不变，全部可选）：
- QUARK_WEBDAV_URL（默认 http://host.docker.internal:8080）
- QUARK_WEBDAV_USER（默认 admin）/ QUARK_WEBDAV_PASS（默认 admin888）

🔴 跨事件循环教训（AGENTS.md）：**不持有模块级 AsyncClient**——每次操作内联创建
（celery 每任务新 loop，模块级异步资源会炸 "Future attached to a different loop"）。
"""
from __future__ import annotations

import contextlib
import os
from urllib.parse import quote

import httpx

from app.core.runtime.storage.base import ObjectStorage

_DEFAULT_URL = "http://host.docker.internal:8080"
_DEFAULT_USER = "admin"
_DEFAULT_PASS = "admin888"


def _quote_path(path: str) -> str:
    """逐段 URL 编码（保留 /），支持中文与空格文件名。"""
    return "/".join(quote(seg, safe="") for seg in path.split("/") if seg)


class QuarkWebDAVStorage(ObjectStorage):
    """夸克网盘 WebDAV 存储（读侧镜像 / 备份目标；默认不参与写入路由）。"""

    backend = "quark"

    def __init__(
        self,
        base_url: str,
        username: str = _DEFAULT_USER,
        password: str = _DEFAULT_PASS,
        root_dir: str = "saios",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("QuarkWebDAVStorage 需要配置 base_url（QUARK_WEBDAV_URL）")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.root_dir = root_dir.strip("/")
        self.timeout = timeout
        self._transport = transport  # 测试注入 httpx.MockTransport 用；生产恒为 None

    @classmethod
    def from_env(cls, transport: httpx.AsyncBaseTransport | None = None) -> QuarkWebDAVStorage:
        """按旧脚本同名环境变量构造（缺省回退旧默认值）。"""
        return cls(
            base_url=os.environ.get("QUARK_WEBDAV_URL", _DEFAULT_URL),
            username=os.environ.get("QUARK_WEBDAV_USER", _DEFAULT_USER),
            password=os.environ.get("QUARK_WEBDAV_PASS", _DEFAULT_PASS),
            transport=transport,
        )

    def _remote(self, key: str) -> str:
        """远端相对路径（未编码）：{root_dir}/{key}。"""
        key = key.lstrip("/")
        return f"{self.root_dir}/{key}" if self.root_dir else key

    def _url(self, key: str) -> str:
        return f"{self.base_url}/{_quote_path(self._remote(key))}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=(self.username, self.password),
            timeout=self.timeout,
            transport=self._transport,
        )

    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        remote = self._remote(key)
        segments = [s for s in remote.split("/") if s][:-1]
        async with self._client() as client:
            # 确保父目录（WebDAV 自动创建不靠谱，逐级 MKCOL；
            # 已存在时服务器回 405/409 属常态，连同网络噪声一起抑制——PUT 才是真判据）
            for i in range(len(segments)):
                parent = "/".join(segments[: i + 1])
                with contextlib.suppress(httpx.HTTPError):
                    await client.request("MKCOL", f"{self.base_url}/{_quote_path(parent)}")
            resp = await client.put(
                self._url(key), content=data, headers={"Content-Type": content_type}
            )
        if resp.status_code not in (200, 201, 204):
            raise RuntimeError(f"夸克 WebDAV PUT 失败 {resp.status_code}: {resp.text[:200]}")
        return remote

    async def get(self, key: str) -> bytes:
        async with self._client() as client:
            resp = await client.get(self._url(key))
        if resp.status_code == 404:
            raise FileNotFoundError(f"夸克 WebDAV 对象不存在: {key}")
        if resp.status_code != 200:
            raise RuntimeError(f"夸克 WebDAV GET 失败 {resp.status_code}: {resp.text[:200]}")
        return resp.content

    async def delete(self, key: str) -> bool:
        async with self._client() as client:
            resp = await client.delete(self._url(key))
        if resp.status_code in (200, 202, 204):
            return True
        if resp.status_code == 404:
            return False
        raise RuntimeError(f"夸克 WebDAV DELETE 失败 {resp.status_code}: {resp.text[:200]}")

    async def get_url(self, key: str) -> str:
        # 内部定位直链（公网交付仍走平台鉴权 access-url，不直连夸克）
        return self._url(key)
