"""音乐讨论室：多轮对话式创作。"""

from __future__ import annotations

import pytest
from app.providers.base import TextResult
from app.services.provider_resolver import ResolvedTextProvider


class _FakeProvider:
    """记录收到的 prompt/system 并返回固定回复。"""

    def __init__(self) -> None:
        self.last_prompt = ""
        self.last_system = ""

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
        self.last_prompt = prompt
        self.last_system = system
        content = "【主歌1】窗外雨停……\n（创作讨论回复）"
        return TextResult(content=content, model=model, provider="fake")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_discuss_first_round(client, user_token, monkeypatch) -> None:
    """首轮：只给主题 → 返回完整初稿回复；system 人格注入。"""
    fake = _FakeProvider()

    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(fake, "cpa", False, provider_config_id=None, source="fake")

    monkeypatch.setattr(
        "app.api.v1.generations.music.resolve_text_provider", fake_resolver
    )
    r = await client.post(
        "/api/v1/generations/music/discuss",
        headers=_headers(user_token),
        json={"messages": [{"role": "user", "content": "写一首关于深夜加班后回家的歌"}]},
    )
    assert r.status_code == 200
    data = r.json()
    assert "窗外雨停" in data["reply"]
    assert data["provider"] == "cpa"
    assert "音乐讨论室" in fake.last_system  # 人格系统提示已注入
    assert "用户：写一首关于深夜加班后回家的歌" in fake.last_prompt


@pytest.mark.asyncio
async def test_discuss_multiturn_context(client, user_token, monkeypatch) -> None:
    """多轮：历史上下文随请求传递，AI 能看到上一轮助手回复。"""
    fake = _FakeProvider()

    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(fake, "cpa", False, provider_config_id=None, source="fake")

    monkeypatch.setattr(
        "app.api.v1.generations.music.resolve_text_provider", fake_resolver
    )
    history = [
        {"role": "user", "content": "写一首古风思乡的歌"},
        {"role": "assistant", "content": "【副歌】家书万里……"},
        {"role": "user", "content": "副歌再含蓄一点，不要直说想家"},
    ]
    r = await client.post(
        "/api/v1/generations/music/discuss",
        headers=_headers(user_token),
        json={"messages": history, "style": "古风"},
    )
    assert r.status_code == 200
    # 历史两轮 + 最新要求都在 prompt 里
    assert "写一首古风思乡的歌" in fake.last_prompt
    assert "家书万里" in fake.last_prompt
    assert "不要直说想家" in fake.last_prompt
    assert "古风" in fake.last_prompt


@pytest.mark.asyncio
async def test_discuss_requires_auth(client) -> None:
    """未登录 → 401。"""
    r = await client.post(
        "/api/v1/generations/music/discuss",
        json={"messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_discuss_empty_messages_rejected(client, user_token) -> None:
    """空消息列表 → 422。"""
    r = await client.post(
        "/api/v1/generations/music/discuss",
        headers=_headers(user_token),
        json={"messages": []},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_roundtable_returns_discussion_and_final(client, user_token, monkeypatch) -> None:
    """多角色圆桌：四角色讨论轮次 + 定稿（歌名/歌词/编曲）。"""
    import json as _json

    from app.providers.base import TextResult
    from app.services.provider_resolver import ResolvedTextProvider

    rt_json = _json.dumps(
        {
            "rounds": [
                {"speaker": "作词人", "content": "意象要新，别用烂月亮"},
                {"speaker": "作曲家", "content": "用 D 小调，副歌五度上行"},
                {"speaker": "制作人", "content": "木吉他加口琴，78 BPM"},
                {"speaker": "乐评人", "content": "副歌没记忆点，重写"},
                {"speaker": "作曲家", "content": "改成三连音节奏解决"},
                {"speaker": "作词人", "content": "副歌金句定为「灯还亮着」"},
            ],
            "final": {
                "title": "归途灯火",
                "lyrics": "【主歌1】夜色…\n【副歌】灯还亮着…",
                "arrangement": "民谣 78 BPM，D 小调，木吉他口琴",
                "style_en": "acoustic folk, 78bpm",
            },
        },
        ensure_ascii=False,
    )

    class _RecordingProvider:
        def __init__(self) -> None:
            self.prompt = ""

        async def generate(self, prompt: str, model: str = "", **kwargs):
            self.prompt = prompt
            return TextResult(content=rt_json, model=model, provider="fake")

    rec = _RecordingProvider()

    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(
            rec, "cpa", False, provider_config_id=None, source="fake"
        )

    monkeypatch.setattr(
        "app.api.v1.generations.music.resolve_text_provider", fake_resolver
    )
    r = await client.post(
        "/api/v1/generations/music/roundtable",
        headers=_headers(user_token),
        json={"theme": "归途", "style": "民谣"},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["rounds"]) == 6
    speakers = {x["speaker"] for x in data["rounds"]}
    assert {"作词人", "作曲家", "制作人", "乐评人"} <= speakers
    assert data["final"]["title"] == "归途灯火"
    assert "灯还亮着" in data["final"]["lyrics"]
    # prompt 带上了圆桌人设与主题
    assert "乐评人" in rec.prompt
    assert "归途" in rec.prompt
