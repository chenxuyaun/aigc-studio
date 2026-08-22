"""zarklab.ai 图像 Provider。

对接 zarklab 的 /v1/complete 端点（tool: image, mode: autonomous）：
  POST https://api.zarklab.ai/v1/complete
  X-API-Key: <key>
  {"chat_session_id": "...", "query": "...", "file_ids": [],
   "tool": "image", "mode": "autonomous",
   "tool_params": {"aspect_ratio": "1:1", "num_images": 2, "quality": "High"}}

上游返回的图在 submit 阶段取回（data URL 缓存），poll 时以 data URL 返回，
与 OpenAICompatibleImageProvider 行为一致，便于统一写入资产库。
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
import weakref
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base import ImageProvider

_ZARK_DEFAULT_BASE = "https://api.zarklab.ai"
_ZARK_DEFAULT_MODEL = "zarklab-image"

# 按 base_url 分桶的节流状态（防止密集请求触发上游限流）
# ⚠️ celery worker 每任务新事件循环：锁按 loop 隔离，避免跨循环复用崩溃。
_throttle_locks: dict[str, "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]"] = {}
_throttle_last: dict[str, float] = {}


def _key_lock(key: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    per_loop = _throttle_locks.setdefault(key, weakref.WeakKeyDictionary())
    lock = per_loop.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        per_loop[loop] = lock
    return lock


class ZarklabError(RuntimeError):
    """zarklab 上游调用失败。"""


def _b64_to_bytes(b64: str) -> bytes:
    try:
        return base64.b64decode(b64)
    except Exception as exc:  # noqa: BLE001
        raise ZarklabError(f"base64 解码失败: {str(exc)[:120]}") from exc


async def _fetch_url(url: str, timeout: float) -> tuple[bytes, str]:
    """下载图片 URL 为字节流；相对路径按 base_url 补全。"""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise ZarklabError(f"图片下载 {resp.status_code}: {resp.text[:120]}")
    ctype = (resp.headers.get("content-type") or "image/png").lower()
    return resp.content, ctype


def _extract_image(data: Any) -> tuple[bytes, str] | None:
    """从 zarklab 响应中容错提取一张图 (bytes, mime)。

    兼容字段：url / image_url / images[].url / data[].url / data[].b64_json /
    result / output / image / assets[].url 等常见形态。
    """
    if data is None:
        return None
    if isinstance(data, str):
        if data.startswith("data:"):
            meta, _, b64 = data.partition(",")
            mime = meta.split(";")[0].replace("data:", "") or "image/jpeg"
            return _b64_to_bytes(b64), mime
        if data.startswith(("http://", "https://")):
            return None, ""  # 需要异步下载，调用方处理
        return None
    if not isinstance(data, dict):
        return None

    def _url_entries(*keys: str) -> list[str]:
        out: list[str] = []
        for k in keys:
            v = data.get(k)
            if isinstance(v, str) and v:
                out.append(v)
            elif isinstance(v, list):
                for it in v:
                    if isinstance(it, str) and it:
                        out.append(it)
        return out

    # 1) data URL（base64 内嵌）
    for k in ("image", "image_url", "b64_json", "base64"):
        v = data.get(k)
        if isinstance(v, str) and v.startswith("data:"):
            meta, _, b64 = v.partition(",")
            mime = meta.split(";")[0].replace("data:", "") or "image/jpeg"
            return _b64_to_bytes(b64), mime
        if isinstance(v, str) and v and k == "b64_json":
            return _b64_to_bytes(v), "image/png"
    # 2) 常见 url 字段
    for u in _url_entries("image", "image_url", "url", "result", "output"):
        if u.startswith("data:"):
            meta, _, b64 = u.partition(",")
            mime = meta.split(";")[0].replace("data:", "") or "image/jpeg"
            return _b64_to_bytes(b64), mime
        if u.startswith(("http://", "https://")):
            return None, ""  # 异步下载
    # 3) 嵌套数组：images / data / assets
    for key in ("images", "data", "assets", "outputs", "results"):
        arr = data.get(key)
        if not isinstance(arr, list) or not arr:
            continue
        first = arr[0]
        if isinstance(first, str):
            if first.startswith("data:"):
                meta, _, b64 = first.partition(",")
                mime = meta.split(";")[0].replace("data:", "") or "image/jpeg"
                return _b64_to_bytes(b64), mime
            return None, ""  # url，异步下载
        if isinstance(first, dict):
            item = _extract_image(first)
            if item is not None:
                return item
    return None


class ZarklabImageProvider(ImageProvider):
    """zarklab.ai /v1/complete 图像生成。submit 同步取图缓存，poll 返回 data URL。"""

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        default_model: str = "",
        timeout: float = 180,
    ) -> None:
        self.base_url = (base_url or _ZARK_DEFAULT_BASE).rstrip("/")
        self.api_key = api_key or settings.ZARK_API_KEY or ""
        self.default_model = default_model or _ZARK_DEFAULT_MODEL
        self.timeout = timeout
        self._cache: dict[str, tuple[bytes, str]] = {}

    async def _throttle(self) -> None:
        interval = float(getattr(settings, "ZARK_MIN_INTERVAL", 0) or 0)
        if interval <= 0:
            return
        lock = _key_lock(self.base_url)
        async with lock:
            last = _throttle_last.get(self.base_url, 0.0)
            wait = last + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            _throttle_last[self.base_url] = time.monotonic()

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    async def submit(self, prompt: str, model: str = "", **kwargs: object) -> dict[str, object]:
        if not self.api_key:
            raise ZarklabError("未配置 ZARK_API_KEY")
        target = (model or "").strip() or self.default_model

        # tool_params：aspect_ratio 取调用方传入（或默认 1:1），num_images 默认 1
        aspect = str(kwargs.get("aspect_ratio") or kwargs.get("aspect") or "1:1")
        num = int(kwargs.get("num_images") or kwargs.get("n") or 1)
        quality = str(kwargs.get("quality") or "High")
        chat_session_id = str(kwargs.get("chat_session_id") or f"sess_{uuid.uuid4().hex[:12]}")

        payload: dict[str, object] = {
            "chat_session_id": chat_session_id,
            "query": prompt,
            "file_ids": [],
            "tool": "image",
            "mode": "autonomous",
            "tool_params": {
                "aspect_ratio": aspect,
                "num_images": num,
                "quality": quality,
            },
        }
        try:
            await self._throttle()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/complete",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code != 200:
                    raise ZarklabError(
                        f"zarklab 图像上游 {resp.status_code}: {resp.text[:200]}"
                    )
                data = resp.json()
        except ZarklabError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ZarklabError(str(exc)) from exc

        # 容错提取第一张图
        extracted = _extract_image(data)
        if extracted is None:
            # 兜底：把响应原文也记录，便于排查
            raise ZarklabError(f"zarklab 响应缺少图片数据: {str(data)[:200]}")
        content, mime = extracted
        if not content:
            # 返回的是 url 需要下载：_extract_image 对纯 http url 返回 (None,"")
            url = None
            if isinstance(data, dict):
                for k in ("image", "image_url", "url", "result", "output"):
                    v = data.get(k)
                    if isinstance(v, str) and v.startswith("http"):
                        url = v
                        break
                if url is None:
                    arr = data.get("images") or data.get("data") or data.get("assets") or []
                    if arr and isinstance(arr[0], str) and arr[0].startswith("http"):
                        url = arr[0]
            if url:
                content, mime = await _fetch_url(url, self.timeout)
            else:
                raise ZarklabError(f"zarklab 响应无法解析图片地址: {str(data)[:200]}")

        task_id = str(uuid.uuid4())
        self._cache[task_id] = (content, mime)
        return {"task_id": task_id, "status": "processing", "model": target}

    async def poll(self, task_id: str) -> dict[str, object]:
        if task_id not in self._cache:
            return {"status": "failed", "progress": 0, "error": "任务不存在"}
        content, mime = self._cache.pop(task_id)
        b64 = base64.b64encode(content).decode()
        return {
            "status": "succeeded",
            "progress": 100,
            "image_url": f"data:{mime};base64,{b64}",
            "mime": mime,
        }
