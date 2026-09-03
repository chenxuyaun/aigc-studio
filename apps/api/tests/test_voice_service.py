"""Personal Voice Engine 服务与端点测试（LLM 全 mock，不触网）。

覆盖：建档/读取、手动编辑（manual 优先）、LLM 自动提取（失败降级规则统计）、
语料增删、build_voice_injection 注入文案。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.models.chat_session import ChatSession
from app.models.growth import MemoryEntry
from app.models.text_document import TextDocument
from app.models.voice import VoiceCorpus, VoiceProfile
from app.services import voice_service
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


async def _seed_corpus(db, user_id: str) -> None:
    db.add(
        ChatSession(
            id=f"sess-{user_id}",
            user_id=user_id,
            name="t",
            messages=[
                {"role": "user", "content": "昨天那个接口查了一晚上，结果是配置文件多了一个空格，气死。"},
                {"role": "assistant", "content": "确实气人。"},
                {"role": "user", "content": "帮我写段话：别整那些虚的，直接说重点。"},
            ],
        )
    )
    db.add(
        MemoryEntry(
            user_id=user_id, kind="preference", content="喜欢短句、口语化、有态度的表达"
        )
    )
    db.add(
        TextDocument(
            id=f"doc-{user_id}",
            user_id=user_id,
            title="随笔",
            content="我不太信大词。什么赋能、抓手、闭环，听着就累。说人话不好吗？",
            status="confirmed",
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_get_or_create_profile_creates_and_reuses(sqlite_db) -> None:
    db = sqlite_db
    p1 = await voice_service.get_or_create_profile(db, "u1")
    assert p1.id and p1.user_id == "u1"
    assert p1.voice_dna.get("sentence_length") == "mixed"
    p2 = await voice_service.get_or_create_profile(db, "u1")
    assert p2.id == p1.id
    # 未 commit 的行在同一会话内可见且幂等（StaticPool 共享连接，跨会话也可见）
    async with TestingSessionLocal() as db2:
        p3 = await voice_service.get_profile(db2, "u1")
        assert p3 is not None and p3.id == p1.id


@pytest.mark.asyncio
async def test_update_profile_manual_wins(sqlite_db) -> None:
    db = sqlite_db
    # update_profile 会自动建档（upsert）
    p = await voice_service.update_profile(
        db,
        "u2",
        name="我的口吻",
        dna={
            "sentence_length": "short",
            "preferred": ["短句", "偶尔反问"],
            "avoid": ["套话"],
        },
        samples=[{"title": "范文", "text": "这事挺离谱的，但就是这么发生了。"}],
    )
    assert p.name == "我的口吻"
    assert p.source == "manual"
    assert p.voice_dna["sentence_length"] == "short"
    assert p.voice_dna["vocabulary"] == "simple"  # 缺省字段补默认
    assert p.voice_dna["preferred"] == ["短句", "偶尔反问"]
    assert p.samples[0]["title"] == "范文"


@pytest.mark.asyncio
async def test_auto_extract_llm_success(sqlite_db) -> None:
    db = sqlite_db
    await _seed_corpus(db, "u3")
    dna_json = json.dumps(
        {
            "sentence_length": "short",
            "vocabulary": "simple",
            "formality": "casual",
            "emotion": "restrained",
            "humor": "dry",
            "opinion_strength": "high",
            "preferred": ["短句", "口语词", "有态度"],
            "avoid": ["大词", "套话", "说教"],
            "openings": ["直接开头"],
            "endings": [],
        },
        ensure_ascii=False,
    )

    async def _fake_resolve(db_: object, model: str):
        provider = type("P", (), {})()
        provider.generate = AsyncMock(return_value=_mk_llm_result(dna_json))
        return type("R", (), {"provider": provider, "model": "mock"})()

    with patch.object(voice_service, "resolve_text_provider", side_effect=_fake_resolve):
        p = await voice_service.auto_extract_profile(db, "u3")
    assert p is not None
    assert p.source == "auto"
    assert p.voice_dna["sentence_length"] == "short"
    assert "短句" in p.voice_dna["preferred"]


@pytest.mark.asyncio
async def test_auto_extract_llm_failure_falls_back_to_rules(sqlite_db) -> None:
    db = sqlite_db
    await _seed_corpus(db, "u4")

    async def _fake_resolve(db_: object, model: str):
        provider = type("P", (), {})()
        provider.generate = AsyncMock(return_value=_mk_llm_result("我不是JSON"))
        return type("R", (), {"provider": provider, "model": "mock"})()

    with patch.object(voice_service, "resolve_text_provider", side_effect=_fake_resolve):
        p = await voice_service.auto_extract_profile(db, "u4")
    assert p is not None
    assert p.voice_dna["sentence_length"] in ("short", "medium", "long", "mixed")
    assert p.voice_dna["emotion"] in ("restrained", "expressive")


@pytest.mark.asyncio
async def test_auto_extract_no_corpus_returns_none(sqlite_db) -> None:
    db = sqlite_db
    p = await voice_service.auto_extract_profile(db, "u-empty")
    assert p is None


@pytest.mark.asyncio
async def test_manual_profile_not_overwritten_by_extract(sqlite_db) -> None:
    db = sqlite_db
    await _seed_corpus(db, "u5")
    await voice_service.update_profile(
        db, "u5", dna={"sentence_length": "long", "preferred": ["手动偏爱"]}
    )
    dna_json = json.dumps(
        {"sentence_length": "short", "preferred": ["机器提炼"]}, ensure_ascii=False
    )

    async def _fake_resolve(db_: object, model: str):
        provider = type("P", (), {})()
        provider.generate = AsyncMock(return_value=_mk_llm_result(dna_json))
        return type("R", (), {"provider": provider, "model": "mock"})()

    with patch.object(voice_service, "resolve_text_provider", side_effect=_fake_resolve):
        p = await voice_service.auto_extract_profile(db, "u5")
    assert p is not None
    assert p.source == "manual"
    assert p.voice_dna["sentence_length"] == "long"  # 手动值不被覆盖
    assert "手动偏爱" in p.voice_dna["preferred"]


@pytest.mark.asyncio
async def test_add_and_list_corpus(sqlite_db) -> None:
    db = sqlite_db
    item = await voice_service.add_corpus(db, "u6", "note", "这段文字是我的真实表达。")
    assert item is not None
    item2 = await voice_service.add_corpus(db, "u6", "bad_kind", "非法的 kind 会被归一为 chat。")
    assert item2 is not None and item2.kind == "chat"
    assert await voice_service.add_corpus(db, "u6", "chat", "短") is None
    rows = await voice_service.list_corpus(db, "u6")
    assert len(rows) == 2
    assert rows[0]["kind"] in ("note", "chat")


@pytest.mark.asyncio
async def test_build_voice_injection(sqlite_db) -> None:
    db = sqlite_db
    # 无档案 → 空串
    assert await voice_service.build_voice_injection(db, "u7") == ""

    await voice_service.update_profile(
        db,
        "u7",
        dna={
            "sentence_length": "short",
            "preferred": ["短句", "直接表达判断"],
            "avoid": ["套话", "总结式结尾"],
        },
        samples=[{"title": "范文", "text": "昨晚两点还在查那个接口为什么一直 500。"}],
    )
    text = await voice_service.build_voice_injection(db, "u7")
    assert "文风档案" in text
    assert "短句" in text
    assert "套话" in text
    assert "范文" in text
    assert len(text) <= 900


@pytest.mark.asyncio
async def test_build_voice_injection_no_profile_but_corpus_empty(sqlite_db) -> None:
    db = sqlite_db
    # 有语料但没有档案时也不强制建档
    await _seed_corpus(db, "u8")
    text = await voice_service.build_voice_injection(db, "u8")
    assert text == ""


@pytest.mark.asyncio
async def test_corpus_limit_prunes_oldest(sqlite_db) -> None:
    db = sqlite_db
    for i in range(voice_service._CORPUS_LIMIT + 5):
        await voice_service.add_corpus(db, "u9", "chat", f"第{i}条语料内容用于上限测试。")
    rows = await voice_service.list_corpus(db, "u9", limit=300)
    assert len(rows) <= voice_service._CORPUS_LIMIT
