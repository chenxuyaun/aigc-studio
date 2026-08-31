# -*- coding: utf-8 -*-
"""故障转移链（v3）单元测试：FailoverTextProvider + 媒体候选构建。"""

from __future__ import annotations

import pytest

from app.providers.base import TextResult
from app.providers.failover import FailoverTextProvider


class _Ok:
    def __init__(self, tag: str, delay_chunks: int = 2) -> None:
        self.tag = tag
        self.delay_chunks = delay_chunks

    async def generate(self, prompt, model="default", tools=None, system="", temperature=None, top_p=None, max_tokens=None):
        return TextResult(content=f"ok:{self.tag}:{prompt}", model=model)

    async def stream_generate(self, prompt, model="default", system="", temperature=None, top_p=None, max_tokens=None):
        for i in range(self.delay_chunks):
            yield f"{self.tag}-{i}"


class _Boom:
    def __init__(self, msg: str = "upstream down") -> None:
        self.msg = msg

    async def generate(self, *a, **kw):
        raise RuntimeError(self.msg)

    async def stream_generate(self, *a, **kw):
        raise RuntimeError(self.msg)
        yield  # pragma: no cover


@pytest.mark.anyio
async def test_generate_falls_back():
    fp = FailoverTextProvider([_Boom("first dead"), _Ok("second")])
    r = await fp.generate("你好", model="m")
    assert r.content == "ok:second:你好"


@pytest.mark.anyio
async def test_generate_all_fail_raises_last():
    fp = FailoverTextProvider([_Boom("e1"), _Boom("e2")])
    with pytest.raises(RuntimeError, match="e2"):
        await fp.generate("x")


@pytest.mark.anyio
async def test_stream_falls_back_before_first_byte():
    fp = FailoverTextProvider([_Boom("dead"), _Ok("live")])
    chunks = [c async for c in fp.stream_generate("hi")]
    assert chunks == ["live-0", "live-1"]


@pytest.mark.anyio
async def test_stream_all_fail():
    fp = FailoverTextProvider([_Boom("a"), _Boom("b")])
    with pytest.raises(RuntimeError):
        async for _ in fp.stream_generate("hi"):
            pass


def test_build_image_provider_dispatch():
    # P0-2 重构: _build_image_provider 已迁到 app.core.runtime.candidate
    from app.core.runtime.candidate import _build_image_provider

    conf = ("http://x/v1", "k", "gemini-3.1-flash-image", "chat_image")
    p = _build_image_provider(conf)
    assert p.__class__.__name__ == "ChatCompletionsImageProvider"
    assert p.default_model == "gemini-3.1-flash-image"

    conf2 = ("http://x/v1", "k", "", "zarklab")
    p2 = _build_image_provider(conf2)
    assert p2.__class__.__name__ == "ZarklabImageProvider"

    conf3 = ("http://x/v1", "k", "", "openai_compatible")
    p3 = _build_image_provider(conf3)
    assert p3.__class__.__name__ == "OpenAICompatibleImageProvider"

    assert _build_image_provider(None) is None
