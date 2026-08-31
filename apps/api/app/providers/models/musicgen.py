"""MusicGen Provider：走 frp 隧道调用 GPU 节点的 MusicGen 服务（saiOS music 槽）。

服务协议（见 .build-tmp/gpu-kit/musicgen/server.py）：
  POST {base}/generate  {"prompt": str, "duration": float}  -> audio/wav 字节
  GET  {base}/health     -> {"ok": true}

与 edge_tts 同款约定：submit 同步生成完，音频以 data URL 返回；
task_runner 的 `poll_result or result` 回退会拿到它。
"""

from __future__ import annotations

import base64
import uuid

import httpx

from app.providers.base import SpeechProvider

DATA_URL_PREFIX = "data:audio/wav;base64,"


class MusicGenProvider(SpeechProvider):
    def __init__(self, base_url: str = "", api_key: str = "", default_model: str = "") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or "none"
        self.default_model = default_model or ""

    async def submit(
        self, text: str, model: str = "", **kwargs: object
    ) -> dict[str, object]:
        if not self.base_url:
            raise RuntimeError("未配置 MusicGen 服务地址")
        try:
            duration = float(kwargs.get("duration") or 10.0)
            duration = max(1.0, min(30.0, duration))
            async with httpx.AsyncClient(timeout=600) as client:
                resp = await client.post(
                    f"{self.base_url}/generate",
                    json={"prompt": text, "duration": duration},
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key not in ("", "none") else None,
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"MusicGen 上游返回 {resp.status_code}: {resp.text[:200]}")
                audio = resp.content
            if not audio:
                raise RuntimeError("MusicGen 未返回音频")
            return {
                "task_id": str(uuid.uuid4()),
                "status": "succeeded",
                "audio_url": DATA_URL_PREFIX + base64.b64encode(audio).decode(),
            }
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"MusicGen 调用失败: {exc!s}") from exc

    async def poll(self, task_id: str) -> dict[str, object]:
        return {"status": "succeeded", "progress": 100}
