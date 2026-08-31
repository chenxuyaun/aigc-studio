"""QuarkWebDAVStorage（P2 新写）：WebDAV 语义 + MockTransport 全链路单测。

覆盖：
- put：MKCOL 建父目录 + PUT 2xx；PUT 500 → RuntimeError
- get：200 内容回读；404 → FileNotFoundError；500 → RuntimeError
- delete：204 → True；404 → False；500 → RuntimeError
- 中文/空格 key 逐段 URL 编码；root_dir 前缀拼接
- from_env 缺省回退旧脚本同名默认值
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.storage.quark_provider import QuarkWebDAVStorage

# 记录请求序列的假 WebDAV 服务器状态
seen: list[tuple[str, str]] = []
objects: dict[str, bytes] = {}


def _reset_state() -> None:
    seen.clear()
    objects.clear()


def _handler(request: httpx.Request) -> httpx.Response:
    method = request.method
    path = request.url.path  # 解码后的路径（作为服务端对象键）
    seen.append((method, request.url.raw_path.decode()))  # 线上真实编码形态
    if method == "MKCOL":
        return httpx.Response(201)
    if method == "PUT":
        objects[path] = request.content
        return httpx.Response(201)
    if method == "GET":
        if path in objects:
            return httpx.Response(200, content=objects[path])
        return httpx.Response(404, text="not found")
    if method == "DELETE":
        if path in objects:
            del objects[path]
            return httpx.Response(204)
        return httpx.Response(404, text="not found")
    return httpx.Response(405)


@pytest.fixture
def store() -> QuarkWebDAVStorage:
    _reset_state()
    return QuarkWebDAVStorage(
        base_url="http://dav.test/",
        username="u",
        password="p",
        root_dir="saios",
        transport=httpx.MockTransport(_handler),
    )


@pytest.mark.asyncio
async def test_put_creates_parents_and_uploads(store: QuarkWebDAVStorage) -> None:
    ret = await store.put("user1/2026/08/封面 图.png", b"png-bytes", "image/png")
    assert ret == "saios/user1/2026/08/封面 图.png"
    # 父目录逐级 MKCOL（saios 根 + user1 + 2026 + 08 共 4 级）+ 1 次 PUT
    methods = [m for m, _ in seen]
    assert methods.count("MKCOL") == 4
    assert methods[-1] == "PUT"
    # 线上请求目标必须是逐段编码形态（中文 + 空格）
    assert seen[-1][1] == "/saios/user1/2026/08/%E5%B0%81%E9%9D%A2%20%E5%9B%BE.png"
    # 服务端对象键（解码后）收到原始字节
    assert objects["/saios/user1/2026/08/封面 图.png"] == b"png-bytes"


@pytest.mark.asyncio
async def test_put_non_2xx_raises(store: QuarkWebDAVStorage) -> None:
    def fail_put(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(500, text="boom")
        return httpx.Response(201)

    store._transport = httpx.MockTransport(fail_put)
    with pytest.raises(RuntimeError, match="PUT 失败 500"):
        await store.put("a/b.txt", b"x")


@pytest.mark.asyncio
async def test_get_roundtrip_and_miss(store: QuarkWebDAVStorage) -> None:
    await store.put("dir/x.txt", b"hello")
    assert await store.get("dir/x.txt") == b"hello"
    with pytest.raises(FileNotFoundError):
        await store.get("dir/missing.txt")


@pytest.mark.asyncio
async def test_get_server_error_raises(store: QuarkWebDAVStorage) -> None:
    def fail_get(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    store._transport = httpx.MockTransport(fail_get)
    with pytest.raises(RuntimeError, match="GET 失败 502"):
        await store.get("anything.txt")


@pytest.mark.asyncio
async def test_delete_semantics(store: QuarkWebDAVStorage) -> None:
    await store.put("dir/y.txt", b"1")
    assert await store.delete("dir/y.txt") is True
    assert await store.delete("dir/y.txt") is False  # 已删 → 404 → False


@pytest.mark.asyncio
async def test_delete_server_error_raises(store: QuarkWebDAVStorage) -> None:
    def fail_del(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    store._transport = httpx.MockTransport(fail_del)
    with pytest.raises(RuntimeError, match="DELETE 失败 500"):
        await store.delete("x.txt")


def test_url_encoding_and_get_url(store: QuarkWebDAVStorage) -> None:
    url = store._url("user/2026/08/文件 名.txt")
    assert url == "http://dav.test/saios/user/2026/08/%E6%96%87%E4%BB%B6%20%E5%90%8D.txt"
    assert json.dumps(url)  # 可序列化（防奇怪对象）


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("QUARK_WEBDAV_URL", "QUARK_WEBDAV_USER", "QUARK_WEBDAV_PASS"):
        monkeypatch.delenv(var, raising=False)
    store = QuarkWebDAVStorage.from_env()
    assert store.base_url == "http://host.docker.internal:8080"
    assert store.username == "admin"
    assert store.password == "admin888"
    with pytest.raises(ValueError, match="base_url"):
        QuarkWebDAVStorage(base_url="")


def test_backend_registered() -> None:
    from app.core.runtime.storage.registry import _VALID_BACKENDS

    assert "quark" in _VALID_BACKENDS
