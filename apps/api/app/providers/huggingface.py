"""HuggingFace 免费推理 API Provider。

无需 API Key 即可使用（有速率限制）；配置 HUGGINGFACE_TOKEN 可提高配额。

- 文本：gpt2 / distilgpt2（免费，英文为主）
- 图像：stabilityai/stable-diffusion-xl-base-1.0（免费配额）
- 语音：facebook/mms-tts-eng（免费）

API 文档：https://huggingface.co/docs/api-inference
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator

import httpx

from app.core.config import settings
from app.providers.base import (
    ImageProvider,
    SpeechProvider,
    TextProvider,
    TextResult,
)

# 新版推理端点：api-inference.huggingface.co 在部分代理网络下被解析为 fake-IP，
# router.huggingface.co 可达（需 HUGGINGFACE_TOKEN 或匿名配额）。
_HF_INFERENCE = "https://router.huggingface.co/hf-inference/models"


def _to_int(value: object, default: int) -> int:
    """上游参数（object）安全转 int；不可转时回落默认值。"""
    return int(value) if isinstance(value, (int, float, str)) else default

# ── 默认模型 ────────────────────────────────────────────────────────

_DEFAULT_TEXT_MODEL = "gpt2"
_DEFAULT_IMAGE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
_DEFAULT_SPEECH_MODEL = "facebook/mms-tts-eng"

# 文本：截断过长的输出，保留可读片段
_MAX_TOKENS = 256


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    token = getattr(settings, "HUGGINGFACE_TOKEN", "") or ""
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ── 文本 Provider ───────────────────────────────────────────────────


class HuggingFaceTextProvider(TextProvider):
    """调用 HuggingFace 推理 API 的 text-generation 任务。"""

    def __init__(self, model: str = _DEFAULT_TEXT_MODEL) -> None:
        self.model = model

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
        target = model or self.model
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": _MAX_TOKENS,
                "do_sample": True,
                "temperature": 0.8,
            },
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{_HF_INFERENCE}/{target}",
                headers=_headers(),
                json=payload,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HF text API {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            # HF 返回格式: [{"generated_text": "..."}]
            if isinstance(data, list) and len(data) > 0:
                text = data[0].get("generated_text", "")
            elif isinstance(data, dict):
                text = data.get("generated_text", str(data))
            else:
                text = str(data)
            # 去除原始 prompt 前缀（gpt2 会把 input 也拼进去）
            if text.startswith(prompt):
                text = text[len(prompt):].strip()
            return TextResult(
                content=text or "（模型返回空文本）", model=target, provider="huggingface"
            )

    async def stream_generate(
        self,
        prompt: str,
        model: str = "",
        system: str = "",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        result = await self.generate(prompt, model)
        # 模拟流式：逐字符产出
        for ch in result.content:
            yield ch
            await asyncio.sleep(0.01)


# ── 图像 Provider ───────────────────────────────────────────────────


class HuggingFaceImageProvider(ImageProvider):
    """调用 HuggingFace 推理 API 的 text-to-image 任务。"""

    def __init__(self, model: str = _DEFAULT_IMAGE_MODEL) -> None:
        self.model = model
        self._cache: dict[str, bytes] = {}  # task_id → image bytes

    async def submit(
        self, prompt: str, model: str = "", **kwargs: object
    ) -> dict[str, object]:
        import uuid

        # 忽略 provider 别名，避免请求 /models/huggingface
        raw = (model or "").strip()
        if raw.lower() in {"", "mock", "huggingface", "openai_compatible"}:
            target = self.model
        else:
            target = raw
        width = _to_int(kwargs.get("width", 768), 768)
        height = _to_int(kwargs.get("height", 768), 768)
        parameters: dict[str, object] = {
            "width": min(width, 1024),
            "height": min(height, 1024),
        }
        if kwargs.get("seed") is not None:
            parameters["seed"] = _to_int(kwargs["seed"], 0)
        cfg = kwargs.get("cfg_scale")
        if isinstance(cfg, (int, float, str)) and cfg not in ("", None):
            parameters["guidance_scale"] = float(cfg)
        if kwargs.get("steps") is not None:
            parameters["num_inference_steps"] = _to_int(kwargs["steps"], 0)
        payload = {
            "inputs": prompt,
            "parameters": parameters,
        }
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{_HF_INFERENCE}/{target}",
                headers=_headers(),
                json=payload,
            )
            if resp.status_code == 401:
                raise RuntimeError(
                    "HuggingFace 需要鉴权：请在 .env 配置 HUGGINGFACE_TOKEN"
                )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"HF image API {resp.status_code} ({target}): {resp.text[:200]}"
                )
            # 偶发返回 JSON 错误而 content-type 仍是 application/json
            ctype = (resp.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                raise RuntimeError(f"HF image API JSON 响应 ({target}): {resp.text[:200]}")
            task_id = str(uuid.uuid4())
            self._cache[task_id] = resp.content
            return {"task_id": task_id, "status": "processing", "model": target}

    async def poll(self, task_id: str) -> dict[str, object]:
        if task_id not in self._cache:
            return {"status": "failed", "progress": 0, "error": "任务不存在"}
        data = self._cache.pop(task_id)
        # 转为 base64 data URL
        b64 = base64.b64encode(data).decode()
        return {
            "status": "succeeded",
            "progress": 100,
            "image_url": f"data:image/png;base64,{b64}",
            "mime": "image/png",
        }


# ── 语音 Provider ───────────────────────────────────────────────────


class HuggingFaceSpeechProvider(SpeechProvider):
    """调用 HuggingFace 推理 API 的 text-to-speech 任务。"""

    def __init__(self, model: str = _DEFAULT_SPEECH_MODEL) -> None:
        self.model = model
        self._cache: dict[str, tuple[bytes, str]] = {}

    async def submit(
        self, text: str, model: str = "", **kwargs: object
    ) -> dict[str, object]:
        import uuid

        target = model or self.model
        payload = {"inputs": text}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{_HF_INFERENCE}/{target}",
                headers=_headers(),
                json=payload,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HF speech API {resp.status_code}: {resp.text[:200]}")
            task_id = str(uuid.uuid4())
            # HF TTS 返回 audio/flac 或 audio/wav
            content_type = resp.headers.get("content-type", "audio/flac")
            self._cache[task_id] = (resp.content, content_type)
            return {"task_id": task_id, "status": "processing"}

    async def poll(self, task_id: str) -> dict[str, object]:
        if task_id not in self._cache:
            return {"status": "failed", "progress": 0, "error": "任务不存在"}
        data, content_type = self._cache.pop(task_id)
        b64 = base64.b64encode(data).decode()
        return {
            "status": "succeeded",
            "progress": 100,
            "audio_url": f"data:{content_type};base64,{b64}",
            "mime": content_type,
        }
