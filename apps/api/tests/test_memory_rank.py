"""方向 B：长期记忆 top-k 相关性检索测试（纯函数 + 注入集成，无网络）。"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.applications.memory_rank import rank_memories
from app.services import growth_service
from tests.conftest import TestingSessionLocal


@pytest_asyncio.fixture
async def sqlite_db():
    """独立内存库会话（与 test_growth 同款）；结束清理本测试用户数据，防共享库污染。"""
    async with TestingSessionLocal() as s:
        yield s
    from sqlalchemy import delete

    from app.models.growth import MemoryEntry

    async with TestingSessionLocal() as s:
        await s.execute(
            delete(MemoryEntry).where(
                MemoryEntry.user_id.in_(["u-rank-1", "u-rank-2"])
            )
        )
        await s.commit()


# ── 纯函数：相关性排序 ──


def test_rank_prefers_relevant_memory() -> None:
    contents = [
        "用户有一辆红色的轿车，常开车上班",  # 旧，无关
        "用户喜欢喝手冲咖啡，讨厌速溶",  # 中
        "用户在学吉他",  # 新，无关
    ]
    idx = rank_memories("帮我推荐一款咖啡豆，我平时喜欢喝咖啡", contents, k=2)
    assert 1 in idx, f"咖啡记忆必须入选: {idx}"
    assert 2 in idx or 0 in idx  # 新近度保底补位


def test_rank_empty_query_is_pure_recency() -> None:
    contents = ["a", "b", "c", "d", "e"]
    idx = rank_memories("", contents, k=3)
    assert idx == [0, 1, 2]


def test_rank_k_bounds() -> None:
    assert rank_memories("q", ["x"], k=0) == []
    assert rank_memories("q", [], k=5) == []
    idx = rank_memories("q", ["a", "b", "c"], k=99)
    assert idx == [0, 1, 2]


def test_rank_deterministic() -> None:
    contents = ["内容甲", "内容乙", "内容丙"] * 3
    r1 = rank_memories("相同", contents, k=4)
    r2 = rank_memories("相同", contents, k=4)
    assert r1 == r2


# ── 集成：build_memory_injection 走 top-k ──


@pytest.mark.asyncio
async def test_build_injection_ranks_by_query(sqlite_db) -> None:
    db = sqlite_db
    from app.models.growth import MemoryEntry

    uid = "u-rank-1"
    rows = [
        MemoryEntry(user_id=uid, kind="fact", content="用户的车是红色的"),
        MemoryEntry(user_id=uid, kind="preference", content="用户最爱喝手冲咖啡，不加糖"),
        MemoryEntry(user_id=uid, kind="event", content="用户上周去了海边旅行"),
    ]
    db.add_all(rows)
    await db.commit()

    text = await growth_service.build_memory_injection(
        db, uid, "帮我挑一款咖啡豆", k=1
    )
    assert "咖啡" in text
    assert "海边" not in text, "无关记忆不应被 top-1 命中"


@pytest.mark.asyncio
async def test_build_injection_no_query_keeps_recency(sqlite_db) -> None:
    db = sqlite_db
    from app.models.growth import MemoryEntry

    uid = "u-rank-2"
    db.add_all(
        [
            MemoryEntry(user_id=uid, kind="fact", content=f"记忆条目{i}")
            for i in range(3)
        ]
    )
    await db.commit()
    text = await growth_service.build_memory_injection(db, uid, "", k=2)
    assert "记忆条目" in text
