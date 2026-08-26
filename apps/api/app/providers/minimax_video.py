"""批14：MiniMax Hailuo（H3）视频生成 provider。

API 参考（platform.minimax.io 实测校订版）：
- 提交：POST {base}/v2/video_generation  Bearer key
  body: model="MiniMax-H3", content=[{type:"text",text:prompt}],
        resolution("768P"|"2K"), duration(秒), ratio
  → {"task_id": "..."}
- 查询：GET {base}/v1/query/video_generation?task_id=...
  status ∈ Preparing/Processing/Success/StreamFailed/Failed；Success 带 file_id
- 取文件：GET {base}/v1/files/retrieve?file_id=...&purpose=video_generation... 实际以查询响应为准：
  部分版本直接在 query 响应给 download_url；否则经 files/retrieve 换取 file.download_url

与 ComfyUIProvider 同款约定：submit→{task_id,status}，poll(阻塞轮询)→{status, video_url}。
base_url 默认 https://api.minimax.io；api_key 必填。
"""

from __future__ import annotations

import asyncio
import os

import httpx

from app.providers.base import VideoProvider

_DEFAULT_BASE = "https://api.minimax.io"
_MODEL = "MiniMax-H3"


class MinimaxVideoProvider(VideoProvider):
    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        default_model: str = "",
    ) -> None:
        self.base_url = (base_url or _DEFAULT_BASE).rstrip("/")
        self.api_key = api_key or ""
        self.default_model = default_model or _MODEL

    # ── 提交 ──────────────────────────────────────────────
    async def submit(
        self, text: str, model: str = "", **kwargs: object
    ) -> dict[str, object]:
        if not self.api_key:
            return {"task_id": "", "status": "failed", "error": "未配置 MiniMax API Key"}
        resolution = str(kwargs.get("resolution") or "768P")
        try:
            duration = int(float(str(kwargs.get("duration") or kwargs.get("duration_seconds") or 6)))
        except ValueError:
            duration = 6
        ratio = str(kwargs.get("ratio") or "16:9")
        body: dict[str, object] = {
            "model": model or self.default_model,
            "content": [{"type": "text", "text": text}],
            "resolution": resolution,
            "duration": duration,
            "ratio": ratio,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/v2/video_generation",
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
            err = data.get("base_resp") or {}
            if isinstance(err, dict) and err.get("status_code") not in (0, None):
                return {"task_id": "", "status": "failed", "error": str(err.get("status_msg") or err)[:200]}
            task_id = str(data.get("task_id") or "")
            if not task_id:
                return {"task_id": "", "status": "failed", "error": f"MiniMax 未返回 task_id: {str(data)[:160]}"}
            return {"task_id": task_id, "status": "running"}
        except Exception as exc:  # noqa: BLE001
            return {"task_id": "", "status": "failed", "error": str(exc)[:200]}

    # ── 阻塞轮询（与 comfyui 同款：Preparing/Processing 继续，Success 取文件）──
    async def poll(self, task_id: str, timeout: float = 900.0) -> dict[str, object]:
        if not self.api_key:
            return {"status": "failed", "error": "未配置 MiniMax API Key"}
        import time as _time

        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(
                        f"{self.base_url}/v1/query/video_generation",
                        params={"task_id": task_id},
                        headers={"Authorization": f"Bearer {self.api_key}"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                err = data.get("base_resp") or {}
                if isinstance(err, dict) and err.get("status_code") not in (0, None):
                    return {"status": "failed", "error": str(err.get("status_msg") or err)[:200]}
                status = str((data.get("status") or "")).lower()
                if status == "success":
                    url = await self._resolve_file_url(task_id, data)
                    if url:
                        return {"status": "succeeded", "video_url": url}
                    return {"status": "failed", "error": "MiniMax 成功但未取到下载地址"}
                if status in ("", "preparing", "processing"):
                    await asyncio.sleep(10)  # H3 典型 1-4 分钟
                    continue
                return {"status": "failed", "error": f"MiniMax 状态 {data.get('status')}"}
            except Exception:  # noqa: BLE001 — 网络抖动重试下一轮
                await asyncio.sleep(10)
        return {"status": "failed", "error": f"MiniMax 生成超时({timeout}s)"}

    async def _resolve_file_url(self, task_id: str, query_data: dict) -> str:
        """优先用 query 响应里的 download_url/file_id，必要时走 files/retrieve。"""
        direct = str(
            (query_data.get("file") or {}).get("download_url")
            or query_data.get("download_url")
            or ""
        )
        if direct:
            return direct
        file_id = str(query_data.get("file_id") or "")
        if not file_id:
            return ""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/v1/files/retrieve",
                params={"file_id": file_id, "purpose": "video_generation", "task_id": task_id},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            info = resp.json()
        f = info.get("file") or {}
        return str(f.get("download_url") or "")


def default_base() -> str:
    return os.environ.get("MINIMAX_BASE_URL", _DEFAULT_BASE)
