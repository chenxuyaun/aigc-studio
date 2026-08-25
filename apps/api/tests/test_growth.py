"""批8+9：成长日记 + 长期记忆服务与端点测试（LLM 全 mock，不触网）。"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.models.chat_session import ChatSession
from app.models.growth import GrowthDiary, MemoryEntry
from app.services import growth_service
from tests.conftest import TestingSessionLocal


@pytest_asyncio.fixture
async def sqlite_db():
    """独立内存库会话（与 client 同一套 StaticPool 数据）。"""
    async with TestingSessionLocal() as s:
        yield s


def _mk_llm_result(content: str) -> Any:
    obj = type("R", (), {})
    inst = obj()
    inst.content = content
    inst.tool_calls = None
    inst.reasoning = ""
    return inst


_REFLECT_JSON = json.dumps(
    {
        "summary": "AI 帮用户写了生日祝福",
        "lessons": ["纯文本创作不需要调工具"],
        "highlights": ["回答一次通过"],
        "memories": [
            {"kind": "preference", "content": "喜欢简洁的祝福文案"},
            {"kind": "fact", "content": "在准备朋友生日"},
            {"kind": "bad_kind", "content": "应被过滤"},
            {"kind": "event", "content": ""},
        ],
    },
    ensure_ascii=False,
)


def _mk_session(user_id: str, session_id: str, n: int = 8) -> ChatSession:
    msgs: list[dict[str, Any]] = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"问题{i}"})
        msgs.append({"role": "assistant", "content": f"回答{i}"})
    return ChatSession(id=session_id, user_id=user_id, name="t", messages=msgs)


@pytest.mark.asyncio
async def test_reflect_creates_diary_and_memories(sqlite_db) -> None:
    db = sqlite_db
    s = _mk_session("u1", "s-1")
    db.add(s)
    await db.commit()

    with patch(
        "app.services.growth_service.resolve_text_provider"
    ) as rp:
        resolved = type("R", (), {})()
        resolved.provider = AsyncMock()
        resolved.provider.generate = AsyncMock(return_value=_mk_llm_result(_REFLECT_JSON))
        resolved.model = "m"
        rp.return_value = resolved
        out = await growth_service.reflect_session(db, "u1", "s-1")

    assert out is not None
    assert out["summary"].startswith("AI 帮")
    diaries = (await db.execute(GrowthDiary.__table__.select())).fetchall()
    assert len(diaries) == 1
    mems = (await db.execute(MemoryEntry.__table__.select())).fetchall()
    # bad_kind 与空 content 被过滤 → 只剩 preference + fact
    kinds = sorted(m[0].kind if hasattr(m[0], "kind") else m["kind"] for m in []) or [
        getattr(r, "kind") for r in mems
    ]
    assert set(kinds) == {"preference", "fact"}
    assert len(mems) == 2


@pytest.mark.asyncio
async def test_reflect_throttles_on_few_new_messages(sqlite_db) -> None:
    db = sqlite_db
    db.add(_mk_session("u1", "s-2"))
    db.add(
        GrowthDiary(
            user_id="u1", session_id="s-2", summary="旧", lessons=[], highlights=[], msg_count=16
        )
    )
    await db.commit()

    with patch("app.services.growth_service.resolve_text_provider") as rp:
        rp.side_effect = AssertionError("节流命中就不该调 LLM")
        out = await growth_service.reflect_session(db, "u1", "s-2")
    assert out is None


@pytest.mark.asyncio
async def test_reflect_runs_again_after_enough_new_messages(sqlite_db) -> None:
    db = sqlite_db
    db.add(_mk_session("u1", "s-3"))  # 16 条 user/assistant
    db.add(
        GrowthDiary(
            user_id="u1", session_id="s-3", summary="旧", lessons=[], highlights=[], msg_count=8
        )
    )
    await db.commit()

    with patch("app.services.growth_service.resolve_text_provider") as rp:
        resolved = type("R", (), {})()
        resolved.provider = AsyncMock()
        resolved.provider.generate = AsyncMock(return_value=_mk_llm_result(_REFLECT_JSON))
        resolved.model = "m"
        rp.return_value = resolved
        out = await growth_service.reflect_session(db, "u1", "s-3")
    assert out is not None  # 新增 8 条 ≥ 阈值 4


@pytest.mark.asyncio
async def test_memory_injection_builds_prompt(sqlite_db) -> None:
    db = sqlite_db
    db.add(MemoryEntry(user_id="u9", kind="preference", content="喜欢赛博朋克风格"))
    db.add(MemoryEntry(user_id="u9", kind="event", content="下周答辩"))
    db.add(MemoryEntry(user_id="other", kind="fact", content="别人的记忆不该出现"))
    await db.commit()

    text = await growth_service.build_memory_injection(db, "u9")
    assert "[偏好] 喜欢赛博朋克风格" in text
    assert "[事件] 下周答辩" in text
    assert "别人的记忆" not in text


@pytest.mark.asyncio
async def test_memory_injection_empty_when_no_memories(sqlite_db) -> None:
    text = await growth_service.build_memory_injection(sqlite_db, "nobody")
    assert text == ""


def test_parse_json_block_variants() -> None:
    assert growth_service._parse_json_block('{"a":1}') == {"a": 1}
    assert growth_service._parse_json_block('```json\n{"a":1}\n```') == {"a": 1}
    assert growth_service._parse_json_block("前置说明 {\"a\": 2} 后缀") == {"a": 2}
    assert growth_service._parse_json_block("不是 json") is None


@pytest.mark.asyncio
async def test_reflect_silent_on_llm_garbage(sqlite_db) -> None:
    db = sqlite_db
    db.add(_mk_session("u1", "s-4"))
    await db.commit()
    with patch("app.services.growth_service.resolve_text_provider") as rp:
        resolved = type("R", (), {})()
        resolved.provider = AsyncMock()
        resolved.provider.generate = AsyncMock(return_value=_mk_llm_result("模型抽风输出"))
        resolved.model = "m"
        rp.return_value = resolved
        out = await growth_service.reflect_session(db, "u1", "s-4")
    assert out is None  # 解析失败 → 不写日记不报错
