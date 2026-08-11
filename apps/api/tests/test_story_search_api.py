"""项目内搜索 + 知识库注入生成。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from app.core.database import Base
from app.services import story_forge
from sqlalchemy import select

from tests.conftest import TestingSessionLocal, _test_engine


@pytest_asyncio.fixture
async def db_session():
    """独立测试库会话（conftest 的内存 SQLite，StaticPool）。"""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # 幂等建表
    async with TestingSessionLocal() as session:
        yield session


async def _mk_project(client, token: str, title: str = "雨夜谜案") -> str:
    r = await client.post(
        "/api/v1/story/projects",
        json={"title": title, "genre": "推理", "synopsis": "暴雨封锁的别墅里发生了密室杀人案。"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


@pytest.mark.asyncio
async def test_project_search_finds_chapters(client, admin_token) -> None:
    """项目内搜索命中章节正文，meta 带 chapter_no。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    pid = await _mk_project(client, admin_token)
    r = await client.post(
        f"/api/v1/story/projects/{pid}/chapters",
        json={"chapter_no": 3, "title": "第三章 时间线破绽", "outline": "死亡时间的矛盾浮出"},
        headers=headers,
    )
    cid = r.json()["chapter"]["id"]
    # 写入正文（模拟已完成章节）
    r = await client.put(
        f"/api/v1/story/chapters/{cid}",
        json={"content": "魏延之的排班表显示他当夜本应在手术，却被人用假急诊调走。"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    r = await client.get(
        f"/api/v1/story/projects/{pid}/search", params={"q": "排班表"}, headers=headers
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) >= 1
    hit = next(i for i in items if i["meta"].get("chapter_no") == 3)
    assert hit["scope"] == "story"
    assert "排班表" in hit["snippet"]


@pytest.mark.asyncio
async def test_project_search_includes_knowledge(client, admin_token) -> None:
    """项目搜索同时检索本人知识库文档。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    pid = await _mk_project(client, admin_token)
    await client.post(
        "/api/v1/knowledge/documents",
        json={"title": "审问技巧", "content": "对质场景要让证词互相矛盾，暴露诡计破绽。"},
        headers=headers,
    )
    r = await client.get(
        f"/api/v1/story/projects/{pid}/search", params={"q": "证词矛盾"}, headers=headers
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["scope"] == "knowledge" for i in items)


@pytest.mark.asyncio
async def test_project_search_isolated(client, admin_token, user_token) -> None:
    """其他用户的项目搜索不可见（项目不存在 → 空）。"""
    user_h = {"Authorization": f"Bearer {user_token}"}
    pid = await _mk_project(client, admin_token)
    r = await client.get(
        f"/api/v1/story/projects/{pid}/search", params={"q": "密室"}, headers=user_h
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0


# ==== 知识库注入生成 ====


@pytest.mark.asyncio
async def test_knowledge_refs_injected_into_chapter_prompt(db_session, monkeypatch) -> None:
    """配置 knowledge_doc_ids 后，_build_chapter_prompt 注入【参考资料】。"""
    from app.models.story_chapter import StoryChapter
    from app.models.story_project import StoryProject
    from app.models.text_document import TextDocument

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        db.add(
            StoryProject(
                id="p-know1",
                user_id="u1",
                title="密室小说",
                synopsis="别墅密室案",
                settings='{"knowledge_doc_ids": ["doc-honkaku"]}',
                status="drafting",
            )
        )
        db.add(
            StoryChapter(
                id="c-know1",
                project_id="p-know1",
                user_id="u1",
                chapter_no=1,
                title="第一章",
                outline="发现尸体",
                status="outline",
            )
        )
        db.add(
            TextDocument(
                id="doc-honkaku",
                user_id="u1",
                title="本格推理指南",
                content="发现尸体是本格推理的起点：本格推理的核心是公平性，读者与侦探拥有相同线索，逻辑必须严密。",
            )
        )
        await db.commit()

        project = (
            await db.execute(select(StoryProject).where(StoryProject.id == "p-know1"))
        ).scalar_one()
        chapter = (
            await db.execute(select(StoryChapter).where(StoryChapter.id == "c-know1"))
        ).scalar_one()
        _system_prompt, user_prompt, _wb = await story_forge._build_chapter_prompt(
            db, "u1", project, chapter, []
        )
        assert "【参考资料" in user_prompt
        assert "本格推理" in user_prompt

        # 未配置文档 → 无参考资料段
        project.settings = "{}"
        await db.commit()
        _sp, user_prompt2, _wb2 = await story_forge._build_chapter_prompt(
            db, "u1", project, chapter, []
        )
        assert "【参考资料" not in user_prompt2


@pytest.mark.asyncio
async def test_outline_prompt_includes_knowledge_refs(db_session, monkeypatch) -> None:
    """generate_outline 注入知识库片段。"""
    from app.models.story_project import StoryProject
    from app.models.text_document import TextDocument

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as db:
        db.add(
            StoryProject(
                id="p-know2",
                user_id="u1",
                title="本格小说",
                synopsis="封闭环境下的交换杀人",
                settings='{"knowledge_doc_ids": ["doc-guide"]}',
                status="drafting",
            )
        )
        db.add(
            TextDocument(
                id="doc-guide",
                user_id="u1",
                title="推理小说创作方法论",
                content="交换杀人的重点是「交换是否真实存在」，线索比例遵循 40-40-20。",
            )
        )
        await db.commit()

        # 直接验证 _knowledge_refs 的产出
        project = (
            await db.execute(select(StoryProject).where(StoryProject.id == "p-know2"))
        ).scalar_one()
        refs = await story_forge._knowledge_refs(db, "u1", project, "交换杀人")
        assert "交换杀人" in refs
        assert "【参考资料" in refs
