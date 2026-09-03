"""Style Reference MCP 工具测试：get_voice_profile / add_voice_sample。

mcp/server.py 的 AsyncSessionLocal 是模块级绑定（conftest 替换不到），
测试里显式 patch 到测试库。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio

import app.mcp.server as mcp_server
from app.mcp.server import get_voice_profile, add_voice_sample
from app.services import voice_service
from tests.conftest import TestingSessionLocal


@pytest_asyncio.fixture
async def admin_id():
    """测试库只建表不 seed（seed 在 client fixture 里）——自插 admin 用户。"""
    from app.models.user import User

    async with TestingSessionLocal() as s:
        row = (
            await s.execute(
                User.__table__.select().where(User.__table__.c.username == "admin")
            )
        ).first()
        if row:
            return str(row.id)
        from app.core.security import hash_password

        u = User(
            username="admin",
            email="admin@test.local",
            password_hash=hash_password("admin123"),
            role="admin",
        )
        s.add(u)
        await s.commit()
        return str(u.id)


@pytest.mark.asyncio
async def test_get_voice_profile_no_profile(admin_id) -> None:
    with patch.object(mcp_server, "AsyncSessionLocal", TestingSessionLocal):
        out = await get_voice_profile(ctx=None)
    assert out == {"exists": False}


@pytest.mark.asyncio
async def test_get_voice_profile_returns_dna_and_samples(admin_id) -> None:
    async with TestingSessionLocal() as s:
        await voice_service.update_profile(
            s,
            admin_id,
            dna={
                "sentence_length": "short",
                "preferred": ["短句", "直接表达判断"],
                "avoid": ["套话"],
            },
            samples=[{"title": "A", "text": "昨晚两点还在查那个接口。"}],
        )
    with patch.object(mcp_server, "AsyncSessionLocal", TestingSessionLocal):
        out = await get_voice_profile(ctx=None)
    assert out["exists"] is True
    assert out["voice_dna"]["sentence_length"] == "short"
    assert "短句" in out["voice_dna"]["preferred"]
    assert out["samples"][0]["text"].startswith("昨晚")


@pytest.mark.asyncio
async def test_add_voice_sample_stores_corpus(admin_id) -> None:
    with patch.object(mcp_server, "AsyncSessionLocal", TestingSessionLocal):
        out = await add_voice_sample(
            text="我的风格是短句、直接、不爱铺垫，这句话算是一个例子。", kind="note", ctx=None
        )
    assert out["ok"] is True
    async with TestingSessionLocal() as s:
        items = await voice_service.list_corpus(s, admin_id)
    assert any("短句" in i["text"] for i in items)


@pytest.mark.asyncio
async def test_add_voice_sample_too_short(admin_id) -> None:
    with patch.object(mcp_server, "AsyncSessionLocal", TestingSessionLocal):
        out = await add_voice_sample(text="短", kind="note", ctx=None)
    assert "error" in out


def test_voice_tools_registered_in_openai_tools() -> None:
    names = {t["function"]["name"] for t in mcp_server._openai_tools()}
    assert "get_voice_profile" in names
    assert "add_voice_sample" in names
