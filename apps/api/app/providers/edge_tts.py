"""Edge TTS 语音 Provider：微软 Edge 免费 TTS（无需 Key、无调用限制）。

生成结果以 data URL 返回（audio/mpeg base64），由 task_runner 的 _download_media
直接解码存入 storage，不依赖任何外部服务。
"""

from __future__ import annotations

import base64
import io
import uuid

from app.providers.base import SpeechProvider

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
MAX_CHARS = 4000  # Edge TTS 单次限制；超出截断（避免任务失败）


class EdgeTTSSpeechProvider(SpeechProvider):
    async def submit(
        self, text: str, model: str = "edge_tts", **kwargs: object
    ) -> dict[str, object]:
        import edge_tts

        voice = str(kwargs.get("voice") or DEFAULT_VOICE)
        content = text[:MAX_CHARS]
        buf = io.BytesIO()
        # 宿主线程内跑（edge-tts 的 websocket 与 asyncio 兼容，直接 await 即可）
        tts = edge_tts.Communicate(content, voice)
        async for chunk in tts.stream():
            if chunk.get("type") == "audio":
                buf.write(chunk.get("data") or b"")
        audio = buf.getvalue()
        if not audio:
            return {"task_id": "", "status": "failed", "error": "Edge TTS 未返回音频"}
        return {
            "task_id": str(uuid.uuid4()),
            "status": "succeeded",
            "audio_url": "data:audio/mpeg;base64," + base64.b64encode(audio).decode(),
        }

    async def poll(self, task_id: str) -> dict[str, object]:
        return {"status": "succeeded", "progress": 100}
