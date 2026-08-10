"""群聊音乐助手：@AI 写歌 指令 → 群内出歌词 + 多轮打磨。"""

from __future__ import annotations

import json

import pytest
from app.models.asset import Asset
from app.models.roleplay_character import RoleplayCharacter
from app.models.roleplay_chat import RoleplayChat
from app.models.user import User
from app.providers.base import TextResult
from app.services import sessions
from app.services.group_service import create_group
from app.services.music_assistant import MUSIC_TAG, _parse_cmd, is_music_cmd
from app.services.provider_resolver import ResolvedTextProvider
from sqlalchemy import select

from tests.conftest import TestingSessionLocal

_LYRICS_JSON = json.dumps(
    {
        "title": "胡同夏声",
        "lyrics": "【主歌1】胡同的青砖路…\n【副歌】那年夏天的味道…",
        "style_zh": "木吉他指弹，78 BPM，口琴点缀。",
        "style_en": "folk",
        "tips": "suno 用",
    },
    ensure_ascii=False,
)


class _FakeProvider:
    """记录调用参数，首轮返回完整歌词 JSON，讨论轮返回修改文本。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.mode = "compose"

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
        self.calls.append({"prompt": prompt, "system": system})
        if system:
            self.mode = "discuss"
            return TextResult(content="【副歌·修改后】知了在树上叫…", model=model, provider="fake")
        return TextResult(content=_LYRICS_JSON, model=model, provider="fake")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_is_music_cmd_variants() -> None:
    assert is_music_cmd("@AI 写歌：80/90 童年")
    assert is_music_cmd("@AI写歌:异地的思念")
    assert is_music_cmd("@ai 写歌 民谣")
    assert not is_music_cmd("写歌：主题")  # 无 @AI 前缀不触发
    assert not is_music_cmd("@AI 你好")
    assert not is_music_cmd("")


def test_parse_cmd_style_and_mood() -> None:
    text, style, mood = _parse_cmd("@AI 写歌：80/90 童年 民谣 伤感")
    assert text == "80/90 童年"
    assert style == "民谣"
    assert mood == "伤感"

    text2, style2, mood2 = _parse_cmd("@AI写歌: 异地的思念")
    assert text2 == "异地的思念"
    assert style2 == ""
    assert mood2 == ""

    text3, style3, mood3 = _parse_cmd("@ai 写歌 古风")
    assert text3 == ""
    assert style3 == "古风"
    assert mood3 == ""


async def _seed_room_owner() -> str:
    """建一个 is_room 群（群主 user1）+ 一个角色卡（asset + 角色行）。"""
    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        db.add(
            Asset(
                id="char-music-1", user_id=u.id,
                filename="char-music-1.png", storage_key="",
                storage_backend="local", mime_type="image/png", size_bytes=0,
            )
        )
        db.add(
            RoleplayCharacter(
                asset_id="char-music-1", user_id=u.id,
                name="测试角色", description="d", personality="p",
            )
        )
        chat = await sessions.create_chat(
            db, u.id, title="写歌群", character_asset_ids=["char-music-1"],
            group=True, is_room=True,
        )
        await create_group(
            db, owner_id=u.id, chat_id=chat.id, name="写歌群", description=""
        )
        await db.commit()
        return chat.id


def _patch_provider(monkeypatch: pytest.MonkeyPatch, fake: _FakeProvider) -> None:
    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(fake, "cpa", False, provider_config_id=None, source="fake")

    monkeypatch.setattr(
        "app.services.music_assistant.resolve_text_provider", fake_resolver
    )


@pytest.mark.asyncio
async def test_group_music_first_round(client, user_token, monkeypatch) -> None:
    """群里发 @AI 写歌 → 完整歌词回复 + 落库 user/assistant 两条。"""
    chat_id = await _seed_room_owner()
    fake = _FakeProvider()
    _patch_provider(monkeypatch, fake)

    r = await client.post(
        "/api/v1/roleplay/chat",
        headers=_headers(user_token),
        json={
            "character_asset_ids": ["char-music-1"],
            "session_id": chat_id,
            "group": True,
            "author": "旁白",
            "messages": [
                {"role": "user", "content": "@AI 写歌：80/90 童年 民谣"}
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["reply"].startswith(MUSIC_TAG)
    assert "胡同夏声" in data["reply"]
    assert data["music"] is True
    assert data["character"]["names"] == ["AI 音乐助手"]
    # 首轮：无 system 人格 → compose
    assert len(fake.calls) >= 1
    assert fake.calls[0]["system"] == ""

    async with TestingSessionLocal() as db:
        chat = await db.get(RoleplayChat, chat_id)
        msgs = sessions.chat_messages(chat)  # type: ignore[arg-type]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "@AI 写歌：80/90 童年 民谣"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"].startswith(MUSIC_TAG)


@pytest.mark.asyncio
async def test_group_music_followup_round(client, user_token, monkeypatch) -> None:
    """第二条指令（历史有歌词）→ 讨论轮：带上下文 + 系统人格。"""
    chat_id = await _seed_room_owner()
    fake = _FakeProvider()
    _patch_provider(monkeypatch, fake)

    # 第一轮出歌词
    r1 = await client.post(
        "/api/v1/roleplay/chat",
        headers=_headers(user_token),
        json={
            "character_asset_ids": ["char-music-1"],
            "session_id": chat_id,
            "group": True,
            "messages": [
                {"role": "user", "content": "@AI 写歌：80/90 童年"}
            ],
        },
    )
    assert r1.status_code == 200

    # 第二轮：改副歌（应走 discuss：system 人格注入 + 历史在 prompt 中）
    r2 = await client.post(
        "/api/v1/roleplay/chat",
        headers=_headers(user_token),
        json={
            "character_asset_ids": ["char-music-1"],
            "session_id": chat_id,
            "group": True,
            "messages": [
                {"role": "user", "content": "@AI 写歌：副歌改成知了和分西瓜"}
            ],
        },
    )
    assert r2.status_code == 200
    data2 = r2.json()
    assert "知了在树上叫" in data2["reply"]
    assert fake.calls[1]["system"] != ""  # 讨论人格已注入
    prompt2 = str(fake.calls[1]["prompt"])
    assert "胡同夏声" in prompt2  # 群历史上下文（上一轮歌词）带上了
    assert "副歌改成知了" in prompt2


@pytest.mark.asyncio
async def test_group_music_private_chat_ignored(client, user_token, monkeypatch) -> None:
    """非群（普通会话）发 @AI 写歌 → 不触发音乐助手。"""
    await _seed_room_owner()  # 建角色卡（char-music-1）供私聊引用
    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        chat = await sessions.create_chat(
            db, u.id, title="私聊", character_asset_ids=["char-music-1"],
            group=False, is_room=False,
        )
        await db.commit()
        chat_id = chat.id

    fake = _FakeProvider()
    _patch_provider(monkeypatch, fake)
    r = await client.post(
        "/api/v1/roleplay/chat",
        headers=_headers(user_token),
        json={
            "character_asset_ids": ["char-music-1"],
            "session_id": chat_id,
            "messages": [{"role": "user", "content": "@AI 写歌：主题"}],
        },
    )
    # 普通会话走角色扮演路径（conftest mock provider），不进入音乐助手分支
    data = r.json()
    assert "music" not in data
    assert "Mock" in str(data.get("reply") or "")


@pytest.mark.asyncio
async def test_group_music_requires_auth(client) -> None:
    """未登录 → 401。"""
    r = await client.post(
        "/api/v1/roleplay/chat",
        json={
            "character_asset_ids": ["char-music-1"],
            "messages": [{"role": "user", "content": "@AI 写歌：x"}],
        },
    )
    assert r.status_code == 401
