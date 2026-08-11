"""群聊 AI 导演：@AI 导演 指令 → 群内演出调度 + 总结沉淀。"""

from __future__ import annotations

import pytest
from app.models.asset import Asset
from app.models.roleplay_character import RoleplayCharacter
from app.models.roleplay_chat import RoleplayChat
from app.models.user import User
from app.providers.base import TextResult
from app.services import sessions
from app.services.director_assistant import (
    DIRECTOR_TAG,
    is_director_cmd,
    is_summary_cmd,
)
from app.services.group_service import create_group
from app.services.provider_resolver import ResolvedTextProvider
from sqlalchemy import select

from tests.conftest import TestingSessionLocal


class _FakeProvider:
    """记录调用参数，按 system 区分导演/总结人格。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

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
        if "场记" in system:
            return TextResult(
                content="【第一场·深夜食堂】小雅在灶台前……\n小雅：欢迎光临。",
                model=model,
                provider="fake",
            )
        return TextResult(
            content="【第一场演出指令】场景：深夜食堂·店内·雨夜\n出场：小雅（主导）\n本场目标：引入第一位客人\n节拍：……\n台词提示：小雅先招呼客人。",
            model=model,
            provider="fake",
        )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_is_director_cmd_variants() -> None:
    assert is_director_cmd("@AI 导演：开演")
    assert is_director_cmd("@AI导演 下一场")
    assert is_director_cmd("@ai 导演：总结")
    assert not is_director_cmd("@AI 写歌：x")
    assert not is_director_cmd("导演：开演")
    assert not is_director_cmd("")


def test_is_summary_cmd() -> None:
    assert is_summary_cmd("@AI 导演：总结")
    assert is_summary_cmd("@AI导演: 复盘一下")
    assert is_summary_cmd("@AI 导演：把这两场存档")
    assert not is_summary_cmd("@AI 导演：开演")
    assert not is_summary_cmd("@AI 导演：下一场")


async def _seed_room() -> str:
    """建群（is_room）+ 角色卡（asset + 角色行）。"""
    async with TestingSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "user1"))).scalar_one()
        db.add(
            Asset(
                id="char-dir-1",
                user_id=u.id,
                filename="char-dir-1.png",
                storage_key="",
                storage_backend="local",
                mime_type="image/png",
                size_bytes=0,
            )
        )
        db.add(
            RoleplayCharacter(
                asset_id="char-dir-1",
                user_id=u.id,
                name="小雅",
                description="深夜食堂女店主",
                personality="温柔体贴",
            )
        )
        chat = await sessions.create_chat(
            db,
            u.id,
            title="夜食缘",
            character_asset_ids=["char-dir-1"],
            group=True,
            is_room=True,
        )
        await create_group(db, owner_id=u.id, chat_id=chat.id, name="夜食缘", description="")
        await db.commit()
        return chat.id


def _patch_provider(monkeypatch: pytest.MonkeyPatch, fake: _FakeProvider) -> None:
    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(fake, "cpa", False, provider_config_id=None, source="fake")

    monkeypatch.setattr("app.services.director_assistant.resolve_text_provider", fake_resolver)


@pytest.mark.asyncio
async def test_director_first_scene(client, user_token, monkeypatch) -> None:
    """群里 @AI 导演 → 首场演出指令 + 落库两条消息。"""
    chat_id = await _seed_room()
    fake = _FakeProvider()
    _patch_provider(monkeypatch, fake)

    r = await client.post(
        "/api/v1/roleplay/chat",
        headers=_headers(user_token),
        json={
            "character_asset_ids": ["char-dir-1"],
            "session_id": chat_id,
            "group": True,
            "author": "旁白",
            "messages": [{"role": "user", "content": "@AI 导演：开演"}],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["reply"].startswith(DIRECTOR_TAG)
    assert "演出指令" in data["reply"]
    assert data["director"] is True
    # 导演人格 system 已注入；prompt 含剧组名与角色表
    assert "掌控全局的戏剧导演" in str(fake.calls[0]["system"])
    prompt0 = str(fake.calls[0]["prompt"])
    assert "夜食缘" in prompt0
    assert "小雅" in prompt0

    async with TestingSessionLocal() as db:
        chat = await db.get(RoleplayChat, chat_id)
        msgs = sessions.chat_messages(chat)  # type: ignore[arg-type]
        assert len(msgs) == 2
        assert msgs[0]["content"] == "@AI 导演：开演"
        assert msgs[1]["content"].startswith(DIRECTOR_TAG)


@pytest.mark.asyncio
async def test_director_summary_round(client, user_token, monkeypatch) -> None:
    """@AI 导演：总结 → 场记人格 + 剧本段落落库。"""
    chat_id = await _seed_room()
    fake = _FakeProvider()
    _patch_provider(monkeypatch, fake)

    r = await client.post(
        "/api/v1/roleplay/chat",
        headers=_headers(user_token),
        json={
            "character_asset_ids": ["char-dir-1"],
            "session_id": chat_id,
            "group": True,
            "messages": [{"role": "user", "content": "@AI 导演：总结"}],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "剧本段落" in data["reply"]
    assert "场记" in str(fake.calls[0]["system"])

    async with TestingSessionLocal() as db:
        chat = await db.get(RoleplayChat, chat_id)
        msgs = sessions.chat_messages(chat)  # type: ignore[arg-type]
        assert msgs[-1]["content"].startswith(DIRECTOR_TAG)
        assert "剧本段落" in msgs[-1]["content"]


@pytest.mark.asyncio
async def test_director_private_chat_ignored(client, user_token, monkeypatch) -> None:
    """普通私聊发 @AI 导演 → 走角色扮演，不触发导演。"""
    await _seed_room()  # 建角色卡
    async with TestingSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "user1"))).scalar_one()
        chat = await sessions.create_chat(
            db,
            u.id,
            title="私聊",
            character_asset_ids=["char-dir-1"],
            group=False,
            is_room=False,
        )
        await db.commit()
        chat_id = chat.id

    fake = _FakeProvider()
    _patch_provider(monkeypatch, fake)
    r = await client.post(
        "/api/v1/roleplay/chat",
        headers=_headers(user_token),
        json={
            "character_asset_ids": ["char-dir-1"],
            "session_id": chat_id,
            "messages": [{"role": "user", "content": "@AI 导演：开演"}],
        },
    )
    data = r.json()
    assert "director" not in data
    assert "Mock" in str(data.get("reply") or "")


@pytest.mark.asyncio
async def test_director_requires_auth(client) -> None:
    """未登录 → 401。"""
    r = await client.post(
        "/api/v1/roleplay/chat",
        json={
            "character_asset_ids": ["char-dir-1"],
            "messages": [{"role": "user", "content": "@AI 导演：开演"}],
        },
    )
    assert r.status_code == 401
