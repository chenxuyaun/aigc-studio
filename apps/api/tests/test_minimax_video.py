"""批14：MiniMax Hailuo(H3) 视频 provider 协议测试（httpx mock，不触网）。"""

from __future__ import annotations

import sys
import unittest.mock as mock
from unittest.mock import AsyncMock

sys.path.insert(0, ".")

import pytest

from app.providers.minimax_video import MinimaxVideoProvider


def _resp(status_code=200, json_data=None):
    class _R:
        def __init__(self):
            self._json = json_data

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def json(self):
            return self._json

    return _R()


def _client(get_side_effects=None, post_return=None):
    fake = AsyncMock()
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    if get_side_effects is not None:
        fake.get.side_effect = get_side_effects
    if post_return is not None:
        fake.post.return_value = post_return
    return fake


pytestmark = pytest.mark.asyncio


async def test_submit_no_key_fails_fast() -> None:
    p = MinimaxVideoProvider(base_url="", api_key="")
    r = await p.submit("一只猫")
    assert r["status"] == "failed" and "Key" in str(r["error"])


async def test_submit_returns_task_id() -> None:
    fake = _client(post_return=_resp(json_data={"task_id": "t123"}))
    p = MinimaxVideoProvider(base_url="https://api.minimax.io", api_key="k")
    with mock.patch("app.providers.minimax_video.httpx.AsyncClient", return_value=fake):
        r = await p.submit("一只猫在草地上奔跑", duration=6, resolution="768P")
    assert r["task_id"] == "t123" and r["status"] == "running"
    args, kwargs = fake.post.call_args
    assert args[0] == "https://api.minimax.io/v2/video_generation"
    body = kwargs["json"]
    assert body["model"] == "MiniMax-H3"
    assert body["content"][0]["text"] == "一只猫在草地上奔跑"
    assert body["resolution"] == "768P" and body["duration"] == 6
    assert kwargs["headers"]["Authorization"] == "Bearer k"


async def test_poll_running_then_success_via_file_id() -> None:
    fake = _client(
        get_side_effects=[
            _resp(json_data={"status": "Processing"}),  # 第一轮：生成中
            _resp(json_data={"status": "Success", "file_id": "f9"}),  # 第二轮：完成
            _resp(json_data={"file": {"download_url": "https://cdn/mm.mp4"}}),  # retrieve
        ]
    )
    p = MinimaxVideoProvider(api_key="k")
    with mock.patch("app.providers.minimax_video.httpx.AsyncClient", return_value=fake):
        r = await p.poll("t123")
    assert r["status"] == "succeeded"
    assert r["video_url"] == "https://cdn/mm.mp4"


async def test_poll_failed_status() -> None:
    fake = _client(get_side_effects=[_resp(json_data={"status": "Failed"})])
    p = MinimaxVideoProvider(api_key="k")
    with mock.patch("app.providers.minimax_video.httpx.AsyncClient", return_value=fake):
        r = await p.poll("t1")
    assert r["status"] == "failed"


async def test_poll_timeout_reports_failed() -> None:
    fake = _client(get_side_effects=[_resp(json_data={"status": "Preparing"})] * 50)
    p = MinimaxVideoProvider(api_key="k")
    with mock.patch("app.providers.minimax_video.httpx.AsyncClient", return_value=fake):
        r = await p.poll("t1", timeout=0.05)
    assert r["status"] == "failed" and "超时" in str(r.get("error"))
