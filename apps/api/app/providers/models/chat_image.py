"""Chat 补全式图像 Provider（cpa gemini-3.1-flash-image 等走 /v1/chat/completions 出图的网关）。

背景：cli-proxy-api 的 gemini 图像模型不提供 /v1/images/generations（gpt-image 系才提供），
图像经 chat 接口返回 message.images[].image_url.url（data URL）。
槽位语义：生图槽位决定模型（default_model），请求传入的 model 名仅作参考。
submit 同步取图缓存，poll 返回 data URL——与 ZarklabImageProvider 同款约定。
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base import ImageProvider


class ChatImageError(RuntimeError):
    """chat 图像上游调用失败。"""


class ChatCompletionsImageProvider(ImageProvider):
    """经 /v1/chat/completions 生成图像。"""

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        default_model: str = "",
        timeout: float = 300,
        max_tokens: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.OPENAI_COMPATIBLE_BASE_URL or "").rstrip("/")
        self.api_key = api_key or settings.OPENAI_COMPATIBLE_API_KEY or "none"
        self.default_model = default_model or "gemini-3.1-flash-image"
        self.timeout = timeout
        # OpenRouter 图像模型：默认 max_tokens 高达数万会触发 402（额度不足），
        # 且中国出口直连被区域限制（403）——worker 的 HTTPS_PROXY 走 Clash 即可过区。
        if max_tokens is None and "openrouter" in self.base_url.lower():
            max_tokens = 4000
        self.max_tokens = max_tokens
        self._cache: dict[str, tuple[bytes, str]] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def submit(self, prompt: str, model: str = "", **kwargs: object) -> dict[str, object]:
        import asyncio

        target = self.default_model or (model or "").strip()
        if not target:
            raise ChatImageError("未指定图像模型（default_model 为空）")
        payload: dict[str, object] = {
            "model": target,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        data: dict[str, Any] | None = None
        last_err: ChatImageError | None = None
        # 上游代理链路偶发 EOF / 5xx（实测约 1/3 概率），指数退避重试；4xx 不重试
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    break
                if resp.status_code < 500 and resp.status_code != 429:
                    raise ChatImageError(
                        f"chat 图像上游 {resp.status_code}: {resp.text[:200]}"
                    )
                last_err = ChatImageError(
                    f"chat 图像上游 {resp.status_code}: {resp.text[:200]}"
                )
            except ChatImageError:
                raise
            except Exception as exc:
                last_err = ChatImageError(str(exc))
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
        if data is None:
            raise last_err or ChatImageError("chat 图像上游无响应")

        # 提取 message.images[].image_url.url；兜底 content 直接是 data URL
        urls: list[str] = []
        try:
            msg = data["choices"][0]["message"]
            for im in msg.get("images") or []:
                u = ((im or {}).get("image_url") or {}).get("url") or ""
                if u:
                    urls.append(u)
            content_field = msg.get("content")
            if not urls and isinstance(content_field, str) and content_field.startswith("data:"):
                urls.append(content_field)
        except Exception as exc:
            raise ChatImageError(f"chat 图像响应解析失败: {exc}") from exc
        if not urls:
            raise ChatImageError(f"chat 图像响应缺少图片: {json.dumps(data, ensure_ascii=False)[:200]}")

        first = urls[0]
        if first.startswith("data:"):
            meta, _, b64 = first.partition(",")
            mime = meta.split(";")[0].replace("data:", "") or "image/jpeg"
            try:
                content = base64.b64decode(b64)
            except Exception as exc:
                raise ChatImageError(f"图片 base64 解码失败: {str(exc)[:120]}") from exc
        elif first.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                r2 = await client.get(first)
                if r2.status_code != 200:
                    raise ChatImageError(f"图片下载 {r2.status_code}: {r2.text[:120]}")
                content = r2.content
                mime = (r2.headers.get("content-type") or "image/png").lower()
        else:
            raise ChatImageError(f"不支持的图片地址形态: {first[:80]}")

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
