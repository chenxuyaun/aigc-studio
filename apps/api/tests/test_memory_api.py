"""角色陪伴记忆 API：蒸馏触发/状态、记忆总览、清空、注入开关。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from app.models.character_profile import CharacterProfile
from app.models.roleplay_character import RoleplayCharacter
from app.models.user import User

from tests.conftest import TestingSessionLocal


async def _seed_character() -> None:
    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        db.add(
            RoleplayCharacter(
                asset_id="char-1", user_id=u.id,
                name="测试角色", description="desc", personality="p",
            )
        )
        await db.commit()


def _client_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_distill_requires_text_or_doc(client, user_token) -> None:
    """无 doc_id 且无 text → 400。"""
    await _seed_character()
    r = await client.post(
        "/api/v1/memory/distill",
        headers=_client_headers(user_token),
        json={"asset_id": "char-1"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_distill_character_not_found(client, user_token) -> None:
    """他人/不存在的角色卡 → 404。"""
    r = await client.post(
        "/api/v1/memory/distill",
        headers=_client_headers(user_token),
        json={"asset_id": "char-nobody", "text": "测试文本"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_distill_trigger_and_status(client, user_token, monkeypatch) -> None:
    """触发蒸馏 → profile pending；状态查询返回。"""
    await _seed_character()
    # 测试环境不派发真实任务（避免 LLM 调用）
    monkeypatch.setattr(
        "app.api.v1.memory._dispatch_distill", lambda *a, **k: None
    )
    r = await client.post(
        "/api/v1/memory/distill",
        headers=_client_headers(user_token),
        json={"asset_id": "char-1", "text": "这是一本关于测试角色的书。"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pending"

    r = await client.get(
        "/api/v1/memory/distill/char-1", headers=_client_headers(user_token)
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert r.json()["asset_id"] == "char-1"


@pytest.mark.asyncio
async def test_memory_overview_gateway_absent(client, user_token, monkeypatch) -> None:
    """gateway 不可用时总览降级：档案有值，交互记忆为空，不报错。"""
    await _seed_character()
    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        db.add(
            CharacterProfile(
                asset_id="char-1", user_id=u.id, book_title="测试之书",
                identity="测试身份", status="done",
                relationships="[]", core_memories="[]", book_chunks="[]",
            )
        )
        await db.commit()
    # 禁用 gateway（等价于未配置 endpoint）
    monkeypatch.setattr("app.services.memory_client.settings.TDAI_MEMORY_ENDPOINT", "")

    r = await client.get(
        "/api/v1/memory/char-1", headers=_client_headers(user_token)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] is not None
    assert body["profile"]["identity"] == "测试身份"
    assert body["profile"]["book_title"] == "测试之书"
    assert body["atoms"] == []
    assert body["scenarios"] == []
    assert body["persona"] == ""
    assert body["config"]["inject"] is True


@pytest.mark.asyncio
async def test_memory_config_toggle(client, user_token) -> None:
    """注入开关读写（存角色卡 settings）。"""
    await _seed_character()
    r = await client.put(
        "/api/v1/memory/char-1/config",
        headers=_client_headers(user_token),
        json={"inject": False, "budget": 1500},
    )
    assert r.status_code == 200
    assert r.json()["config"]["inject"] is False
    assert r.json()["config"]["budget"] == 1500

    r = await client.get(
        "/api/v1/memory/char-1/config", headers=_client_headers(user_token)
    )
    assert r.json()["config"]["inject"] is False

    # 恢复
    await client.put(
        "/api/v1/memory/char-1/config",
        headers=_client_headers(user_token),
        json={"inject": True, "budget": 2500},
    )


@pytest.mark.asyncio
async def test_memory_clear_ok(client, user_token, monkeypatch) -> None:
    """清空交互记忆（gateway 缺失时仍返回 ok）。"""
    await _seed_character()
    monkeypatch.setattr("app.services.memory_client.settings.TDAI_MEMORY_ENDPOINT", "")
    r = await client.post(
        "/api/v1/memory/char-1/clear", headers=_client_headers(user_token)
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
