"""批13：GPU 节点 provider（MusicGen / ComfyUI）协议测试（httpx mock，不触网）。"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest

from app.providers.models.comfyui import ComfyUIProvider
from app.providers.models.musicgen import MusicGenProvider

pytestmark = pytest.mark.asyncio


def _resp(status: int = 200, content: bytes = b"", json_data=None):
    class _R:
        status_code = status

        def __init__(self):
            self._content = content
            self._json = json_data

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception(f"HTTP {self.status_code}")

        @property
        def content(self):
            return self._content

        def json(self):
            return self._json

    return _R()


async def test_musicgen_submit_returns_data_url() -> None:
    wav = b"RIFF....fakewav"
    fake = AsyncMock()
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    fake.post.return_value = _resp(200, content=wav)

    p = MusicGenProvider(base_url="http://172.17.0.1:7002")
    with patch("app.providers.models.musicgen.httpx.AsyncClient", return_value=fake):
        r = await p.submit("一首温柔的钢琴曲", duration=8)

    assert r["status"] == "succeeded"
    assert r["audio_url"].startswith("data:audio/wav;base64,")
    assert base64.b64decode(r["audio_url"].split(",", 1)[1]) == wav
    # 请求体：prompt + duration
    args, kwargs = fake.post.call_args
    assert args[0] == "http://172.17.0.1:7002/generate"
    assert kwargs["json"] == {"prompt": "一首温柔的钢琴曲", "duration": 8.0}


async def test_musicgen_submit_no_base_url() -> None:
    p = MusicGenProvider(base_url="")
    with pytest.raises(RuntimeError, match="未配置"):
        await p.submit("x")


async def test_comfyui_submit_and_poll_success() -> None:
    fake = AsyncMock()
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    fake.post.return_value = _resp(200, json_data={"prompt_id": "abc123"})
    fake.get.return_value = _resp(
        200,
        json_data={
            "abc123": {
                "status": {"completed": True},
                "outputs": {
                    "7": {"videos": [{"filename": "saios_wan_0001.mp4", "subfolder": "", "type": "output"}]}
                },
            }
        },
    )

    p = ComfyUIProvider(base_url="http://172.17.0.1:7001")
    with patch("app.providers.models.comfyui.httpx.AsyncClient", return_value=fake):
        sub = await p.submit("一只猫在草地上奔跑", width=480)
        assert sub["task_id"] == "abc123" and sub["status"] == "running"
        # prompt 已注入模板
        posted = fake.post.call_args.kwargs["json"]["prompt"]
        texts = [
            n["inputs"]["text"]
            for n in posted.values()
            if isinstance(n, dict) and n.get("class_type") == "CLIPTextEncode"
        ]
        assert any("一只猫在草地上奔跑" in t for t in texts)

        poll = await p.poll("abc123")
        assert poll["status"] == "succeeded"
        assert poll["video_url"].startswith("http://172.17.0.1:7001/view?filename=")


async def test_comfyui_poll_running_then_completed() -> None:
    """批13：poll 是阻塞轮询——首轮 running 继续等，次轮拿到产出即成功。"""
    fake = AsyncMock()
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    fake.get.side_effect = [
        _resp(200, json_data={"abc123": {}}),  # 第一轮：记录未完成 → continue
        _resp(
            200,
            json_data={
                "abc123": {
                    "status": {"completed": True},
                    "outputs": {"7": {"videos": [{"filename": "saios_wan_0001.mp4", "subfolder": "", "type": "output"}]}},
                }
            },
        ),
    ]
    fake.post.return_value = _resp(200, json_data={"prompt_id": "abc123"})

    p = ComfyUIProvider(base_url="http://172.17.0.1:7001")
    with patch("app.providers.models.comfyui.httpx.AsyncClient", return_value=fake):
        await p.submit("一只猫", width=480)
        r = await p.poll("abc123")
    assert r["status"] == "succeeded"
    assert r["video_url"].startswith("http://172.17.0.1:7001/view?filename=")


async def test_comfyui_poll_timeout_reports_failed() -> None:
    """一直 running → 阻塞到 timeout 如实返回失败（不再无限挂起）。"""
    fake = AsyncMock()
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    fake.get.return_value = _resp(200, json_data={"abc123": {}})

    p = ComfyUIProvider(base_url="http://172.17.0.1:7001")
    with patch("app.providers.models.comfyui.httpx.AsyncClient", return_value=fake):
        r = await p.poll("abc123", timeout=0.05)
    assert r["status"] == "failed"
    assert "超时" in (r.get("error") or "")