import asyncio
import base64
import json
import random
import time
import uuid
from collections.abc import AsyncIterator

import httpx

from app.core.config import settings
from app.providers.base import (
    ImageProvider,
    TextProvider,
    TextResult,
    VideoProvider,
)

_MAX_RETRIES = 3  # 上游 429 限流自动退避重试次数

# 按 base_url 分桶的节流状态（防密集请求触发上游风控，如 Grok anti-bot 403）
_throttle_locks: dict[str, asyncio.Lock] = {}
_throttle_last: dict[str, float] = {}


class ProviderError(RuntimeError):
    """真实 Provider 调用失败（连接、鉴权或上游错误），供上层决定是否回退。"""


class OpenAICompatibleTextProvider(TextProvider):
    """对接 OpenAI 兼容 /chat/completions（Grok 代理、Grok2API、LiteLLM 等）。"""

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        default_model: str = "",
        timeout: float = 60,
    ) -> None:
        self.base_url = (base_url or settings.OPENAI_COMPATIBLE_BASE_URL or "").rstrip("/")
        self.api_key = api_key or settings.OPENAI_COMPATIBLE_API_KEY or "none"
        self.default_model = default_model or settings.OPENAI_COMPATIBLE_MODEL or ""
        self.timeout = timeout

    async def _throttle(self) -> None:
        """同一上游的最小请求间隔（设置 OPENAI_COMPATIBLE_MIN_INTERVAL，秒）。"""
        interval = float(settings.OPENAI_COMPATIBLE_MIN_INTERVAL or 0)
        if interval <= 0:
            return
        key = self.base_url
        lock = _throttle_locks.setdefault(key, asyncio.Lock())
        async with lock:
            last = _throttle_last.get(key, 0.0)
            wait = last + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            _throttle_last[key] = time.monotonic()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _post_retry(
        self, client: httpx.AsyncClient, url: str, payload: dict[str, object]
    ) -> httpx.Response:
        """POST 带 429 自动退避重试（上游限流常见，指数退避 + jitter）。"""
        await self._throttle()
        for attempt in range(_MAX_RETRIES):
            resp = await client.post(url, headers=self._headers(), json=payload)
            if resp.status_code != 429 or attempt >= _MAX_RETRIES - 1:
                return resp
            await asyncio.sleep(2**attempt + random.uniform(0, 1))
        return resp  # 防御：循环理论上必 return，满足类型检查

    async def generate(
        self,
        prompt: str,
        model: str = "",
        tools: list[dict[str, object]] | None = None,
        system: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> TextResult:
        if not self.base_url:
            raise ProviderError("未配置 base_url")
        model = model or self.default_model
        messages: list[dict[str, object]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await self._post_retry(
                    client, f"{self.base_url}/chat/completions", payload
                )
                if resp.status_code != 200:
                    raise ProviderError(f"上游返回 {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                msg = data["choices"][0]["message"]
                tool_calls: list[dict[str, object]] | None = None
                raw_calls = msg.get("tool_calls")
                if isinstance(raw_calls, list):
                    tool_calls = []
                    for tc in raw_calls:
                        fn = tc.get("function") or {}
                        tool_calls.append(
                            {
                                "id": str(tc.get("id") or ""),
                                "name": str(fn.get("name") or ""),
                                "arguments": str(fn.get("arguments") or "{}"),
                            }
                        )
                return TextResult(
                    content=str(msg.get("content") or ""),
                    model=model,
                    provider="openai_compatible",
                    tool_calls=tool_calls,
                )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(str(exc)) from exc

    async def stream_generate(
        self,
        prompt: str,
        model: str = "",
        system: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        if not self.base_url:
            raise ProviderError("未配置 base_url")
        model = model or self.default_model
        messages: list[dict[str, object]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            for attempt in range(_MAX_RETRIES):
                await self._throttle()
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    cm = client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
                    resp = await cm.__aenter__()
                    try:
                        if resp.status_code == 429 and attempt < _MAX_RETRIES - 1:
                            # 限流：退避后重建连接重试
                            await asyncio.sleep(2**attempt + random.uniform(0, 1))
                            continue
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", "replace")[:200]
                            raise ProviderError(f"上游返回 {resp.status_code}: {body}")
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: ") or line == "data: [DONE]":
                                continue
                            try:
                                chunk = json.loads(line[6:])
                                delta = chunk["choices"][0].get("delta", {})
                            except Exception:
                                continue
                            content = delta.get("content")
                            if content:
                                yield content
                        break
                    finally:
                        await cm.__aexit__(None, None, None)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(str(exc)) from exc


def _b64_to_bytes(b64: str) -> bytes:
    """兼容 data: 前缀的 base64 字符串。"""
    import base64

    if "," in b64:
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)


def _to_int(value: object, default: int) -> int:
    """上游参数（object）安全转 int；不可转时回落默认值。"""
    return int(value) if isinstance(value, (int, float, str)) else default


def _rewrite_media_url(url: str, upstream_base: str) -> str:
    """上游返回的 media URL 常指向其容器内 127.0.0.1/localhost；
    按 provider base_url 的 host 改写，保证容器内也能下载。"""
    from urllib.parse import urlparse, urlunparse

    if not url or not url.startswith(("http://", "https://")):
        return url
    try:
        u = urlparse(url)
        if u.hostname not in ("127.0.0.1", "localhost"):
            return url
        p = urlparse(upstream_base)
        if not p.hostname:
            return url
        return urlunparse(
            (p.scheme or u.scheme, p.netloc, u.path, u.params, u.query, u.fragment)
        )
    except ValueError:
        return url


class OpenAICompatibleImageProvider(ImageProvider):
    """对接 OpenAI 兼容 /images/generations（grok2api 等本地网关）。

    上游成功时把图取回进程内缓存，poll 时以 data URL 返回，与
    HuggingFaceImageProvider 行为一致，便于统一写入资产库。
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        default_model: str = "",
        timeout: float = 180,
    ) -> None:
        self.base_url = (base_url or settings.OPENAI_COMPATIBLE_BASE_URL or "").rstrip("/")
        self.api_key = api_key or settings.OPENAI_COMPATIBLE_API_KEY or "none"
        self.default_model = (
            default_model
            or settings.OPENAI_COMPATIBLE_IMAGE_MODEL
            or settings.OPENAI_COMPATIBLE_MODEL
            or "grok-imagine-image"
        )
        self.timeout = timeout
        self._cache: dict[str, tuple[bytes, str]] = {}

    async def _throttle(self) -> None:
        """同一上游的最小请求间隔（设置 OPENAI_COMPATIBLE_MIN_INTERVAL，秒）。"""
        interval = float(settings.OPENAI_COMPATIBLE_MIN_INTERVAL or 0)
        if interval <= 0:
            return
        key = self.base_url
        lock = _throttle_locks.setdefault(key, asyncio.Lock())
        async with lock:
            last = _throttle_last.get(key, 0.0)
            wait = last + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            _throttle_last[key] = time.monotonic()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def submit(
        self, prompt: str, model: str = "", **kwargs: object
    ) -> dict[str, object]:
        if not self.base_url:
            raise ProviderError("未配置 base_url")
        target = (model or "").strip() or self.default_model
        width = _to_int(kwargs.get("width", 1024), 1024)
        height = _to_int(kwargs.get("height", 1024), 1024)
        payload: dict[str, object] = {
            "model": target,
            "prompt": prompt,
            "n": 1,
            "size": f"{width}x{height}",
        }
        if kwargs.get("seed") is not None:
            payload["seed"] = _to_int(kwargs["seed"], 0)
        cfg = kwargs.get("cfg_scale")
        if isinstance(cfg, (int, float, str)) and cfg not in ("", None):
            payload["cfg_scale"] = float(cfg)
        # 图生图：参考图 data URL（grok-imagine-image 支持 image 输入）
        img = kwargs.get("image")
        if isinstance(img, str) and img.startswith("data:"):
            payload["image"] = img
        try:
            await self._throttle()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/images/generations",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code != 200:
                    raise ProviderError(
                        f"图像上游 {resp.status_code} ({target}): {resp.text[:200]}"
                    )
                data = resp.json()
                item = (data.get("data") or [{}])[0]
                b64 = item.get("b64_json")
                url = item.get("url", "")
                if b64:
                    content = _b64_to_bytes(b64)
                    mime = "image/png"
                elif url:
                    content, mime = await self._fetch_url(url)
                else:
                    raise ProviderError(f"图像上游响应缺少图片数据: {str(data)[:160]}")
                task_id = str(uuid.uuid4())
                self._cache[task_id] = (content, mime)
                return {"task_id": task_id, "status": "processing", "model": target}
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(str(exc)) from exc

    async def _fetch_url(self, url: str) -> tuple[bytes, str]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(_rewrite_media_url(url, self.base_url))
            if resp.status_code != 200:
                raise ProviderError(f"图片下载 {resp.status_code}: {resp.text[:120]}")
        ctype = (resp.headers.get("content-type") or "image/png").lower()
        return resp.content, ctype

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


class OpenAICompatibleVideoProvider(VideoProvider):
    """对接 OpenAI 兼容 /videos/generations（grok2api 视频路由）。

    grok2api 已暴露 /videos/generations 端点，但当前账号路由无视频模型
    （探测返回 model_not_found）；等模型/账号恢复后即走真实生成。
    上游任务结构按 OpenAI 兼容风格做宽容解析：submit 拿 task id，
    poll 尝试查询任务；不支持查询时返回 failed 由上层回退 Mock。
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        default_model: str = "",
        timeout: float = 300,
    ) -> None:
        self.base_url = (base_url or settings.OPENAI_COMPATIBLE_BASE_URL or "").rstrip("/")
        self.api_key = api_key or settings.OPENAI_COMPATIBLE_API_KEY or "none"
        self.default_model = (
            default_model or settings.OPENAI_COMPATIBLE_VIDEO_MODEL or "grok-imagine-video"
        )
        self.timeout = timeout
        self._cache: dict[str, tuple[bytes, str]] = {}

    async def _throttle(self) -> None:
        """同一上游的最小请求间隔（设置 OPENAI_COMPATIBLE_MIN_INTERVAL，秒）。"""
        interval = float(settings.OPENAI_COMPATIBLE_MIN_INTERVAL or 0)
        if interval <= 0:
            return
        key = self.base_url
        lock = _throttle_locks.setdefault(key, asyncio.Lock())
        async with lock:
            last = _throttle_last.get(key, 0.0)
            wait = last + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            _throttle_last[key] = time.monotonic()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def submit(
        self, prompt: str, model: str = "", **kwargs: object
    ) -> dict[str, object]:
        if not self.base_url:
            raise ProviderError("未配置 base_url")
        target = (model or "").strip() or self.default_model
        payload: dict[str, object] = {
            "model": target,
            "prompt": prompt,
            "duration": kwargs.get("duration", 5),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/videos/generations",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code != 200:
                    raise ProviderError(
                        f"视频上游 {resp.status_code} ({target}): {resp.text[:200]}"
                    )
                data = resp.json()
                # 宽容解析：id / task_id / data[0].id 均可
                item = data.get("data", [{}])[0] if isinstance(data.get("data"), list) else data
                task_id = str(
                    item.get("id")
                    or item.get("task_id")
                    or data.get("id")
                    or data.get("task_id")
                    or ""
                )
                if not task_id:
                    raise ProviderError(f"视频上游响应缺少任务 id: {str(data)[:160]}")
                return {"task_id": task_id, "status": "processing", "model": target}
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(str(exc)) from exc

    async def poll(self, task_id: str) -> dict[str, object]:
        if not self.base_url:
            return {"status": "failed", "progress": 0, "error": "未配置 base_url"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.base_url}/videos/{task_id}", headers=self._headers()
                )
            if resp.status_code != 200:
                return {
                    "status": "failed",
                    "progress": 0,
                    "error": f"视频任务查询 {resp.status_code}: {resp.text[:120]}",
                }
            data = resp.json()
            status = str(data.get("status") or data.get("state") or "processing").lower()
            if status in ("succeeded", "completed", "done"):
                url = str(data.get("url") or data.get("video_url") or "")
                if not url:
                    return {"status": "failed", "progress": 0, "error": "视频结果缺少 url"}
                content, mime = await self._fetch_video(url)
                return {
                    "status": "succeeded",
                    "progress": 100,
                    "video_url": f"data:{mime};base64,{base64.b64encode(content).decode()}",
                    "mime": mime,
                }
            if status in ("failed", "error", "cancelled"):
                return {"status": "failed", "progress": 0, "error": f"视频任务 {status}"}
            return {"status": "processing", "progress": int(data.get("progress") or 10)}
        except ProviderError:
            raise
        except Exception as exc:
            return {"status": "failed", "progress": 0, "error": str(exc)[:160]}

    async def _fetch_video(self, url: str) -> tuple[bytes, str]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(_rewrite_media_url(url, self.base_url))
            if resp.status_code != 200:
                raise ProviderError(f"视频下载 {resp.status_code}: {resp.text[:120]}")
        ctype = (resp.headers.get("content-type") or "video/mp4").lower()
        return resp.content, ctype
