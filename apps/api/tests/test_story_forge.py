# ruff: noqa: PT018

"""Story Forge 创作引擎服务测试：项目/章节/角色实例 CRUD + 叙事/剧本/大纲/修订/导出。

用 monkeypatch 注入假角色卡与假 provider，不触碰真实存储与上游。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from app.core.database import Base
from app.models.generation_task import GenerationTask
from app.models.serial_schedule import SerialSchedule
from app.services import story_forge
from sqlalchemy import func, select

from tests.conftest import TestingSessionLocal, _test_engine


@pytest_asyncio.fixture
async def db_session():
    """独立测试库会话（conftest 的内存 SQLite，StaticPool）。"""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # 幂等建表
    async with TestingSessionLocal() as session:
        yield session


def _fake_cards(*names: str) -> list[tuple[str, dict]]:
    return [
        (
            f"asset-{i}",
            {
                "name": n,
                "description": f"{n}的外观",
                "personality": "温柔",
                "scenario": "咖啡馆",
                "first_mes": "你好",
                "mes_example": "",
                "alternate_greetings": [],
                "system_prompt": "",
                "post_history_instructions": "",
                "creator_notes": "",
                "tags": [],
                "character_book": {},
                "talkativeness": 0.5,
                "depth_prompt": {},
            },
        )
        for i, n in enumerate(names)
    ]


class _FakeProvider:
    """固定文本 provider（模拟 mock/上游）。"""

    def __init__(self, text: str) -> None:
        self.text = text

    async def generate(self, prompt: str, model: str = "mock", **kw: object) -> object:
        class _R:
            content: str = self.text
            tool_calls: list[object] | None = None

        return _R()


class _FakeResolved:
    def __init__(self, text: str) -> None:
        self.provider = _FakeProvider(text)
        self.model = "mock"


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch, reply: str = "晨星山的山顶笼罩在薄雾中。露娜推开了窗。"
) -> None:
    """注入假角色卡 + 假 provider（所有依赖 resolve 的路径统一走它）。"""
    import app.services.roleplay as rp_mod

    async def _fake_resolver(db: object, model: str) -> _FakeResolved:
        return _FakeResolved(reply)

    async def _fake_load_cards(db: object, uid: str, ids: list[str]) -> list[tuple[str, dict]]:
        return _fake_cards("露娜", "洛根")

    monkeypatch.setattr(rp_mod, "_load_cards", _fake_load_cards)
    monkeypatch.setattr(story_forge.roleplay, "_load_cards", _fake_load_cards)
    monkeypatch.setattr(story_forge, "resolve_text_provider", _fake_resolver)


# ==== 项目 CRUD ====


@pytest.mark.anyio
async def test_project_crud(db_session: object, monkeypatch: pytest.MonkeyPatch) -> None:
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(
        db,
        "u1",
        title="晨星山物语",
        synopsis="少女与黑猫的冒险",
        genre="奇幻",
        character_asset_ids=["asset-0"],
    )
    assert p.id and p.status == "drafting"
    items = await story_forge.list_projects(db, "u1")
    assert len(items) == 1 and items[0]["title"] == "晨星山物语"
    # 更新
    p2 = await story_forge.update_project(
        db, "u1", p.id, {"status": "ongoing", "genre": "奇幻冒险"}
    )
    assert p2 is not None and p2.status == "ongoing"
    # 用户隔离
    assert await story_forge.get_project(db, "other", p.id) is None
    # 删除（级联）
    await story_forge.create_chapter(db, "u1", p.id, title="第一章")
    await story_forge.create_story_character(db, "u1", p.id, name="露娜")
    assert await story_forge.delete_project(db, "u1", p.id) is True
    assert await story_forge.list_chapters(db, "u1", p.id) == []
    assert await story_forge.list_story_characters(db, "u1", p.id) == []


# ==== 章节 CRUD ====


@pytest.mark.anyio
async def test_chapter_crud(db_session: object) -> None:
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="T")
    c1 = await story_forge.create_chapter(db, "u1", p.id, title="第一章")
    c2 = await story_forge.create_chapter(db, "u1", p.id, title="第二章")
    assert c1.chapter_no == 1 and c2.chapter_no == 2  # 自动编号
    c3 = await story_forge.create_chapter(db, "u1", p.id, chapter_no=5, title="插叙")
    assert c3.chapter_no == 5
    await story_forge.update_chapter(db, "u1", c1.id, {"content": "正文内容"})
    got = await story_forge.get_chapter(db, "u1", c1.id)
    assert got is not None and got.status == "done" and got.word_count == 4
    assert await story_forge.delete_chapter(db, "u1", c2.id) is True
    assert await story_forge.get_chapter(db, "u1", c2.id) is None


# ==== 角色实例 CRUD ====


@pytest.mark.anyio
async def test_story_character_crud(db_session: object) -> None:
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="T")
    s = await story_forge.create_story_character(
        db,
        "u1",
        p.id,
        name="露娜",
        role="protagonist",
        goals="登上晨星山",
        skill_ids=["sk1"],
    )
    assert s.skill_ids and json.loads(s.skill_ids) == ["sk1"]
    s2 = await story_forge.update_story_character(
        db, "u1", s.id, {"current_state": "在山顶", "skill_ids": []}
    )
    assert s2 is not None and s2.current_state == "在山顶"
    assert await story_forge.delete_story_character(db, "u1", s.id) is True


# ==== bible 组装（技能注入） ====


@pytest.mark.anyio
async def test_bible_text_injects_skills(
    db_session: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.skill import Skill

    db = db_session  # type: ignore[assignment]
    db.add(Skill(id="sk1", author_id="u1", name="观星", instructions="使用星辰魔法观测天气。"))
    await db.commit()
    p = await story_forge.create_project(db, "u1", title="T")
    await story_forge.create_story_character(
        db,
        "u1",
        p.id,
        name="露娜",
        character_asset_id="asset-0",
        role="protagonist",
        skill_ids=["sk1"],
    )
    text = await story_forge._bible_text(db, "u1", p, _fake_cards("露娜"))
    assert "观星" in text and "星辰魔法" in text
    assert "定位：主角" in text


# ==== 叙事模式生成 ====


@pytest.mark.anyio
async def test_generate_chapter_narrative(
    db_session: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = "第 1 章 启程\n\n晨星山的第一缕光落在露娜肩头。"
    _install_fakes(monkeypatch, reply=reply)
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="晨星山物语", synopsis="冒险")
    c = await story_forge.create_chapter(db, "u1", p.id, title="启程", outline="出发去山顶")
    result = await story_forge.generate_chapter(db, "u1", p.id, c.id)
    assert "error" not in result, result
    # 章节标题前缀被清理，正文落库
    assert "第 1 章 启程" not in result["content"]
    assert "晨星山" in result["content"]
    got = await story_forge.get_chapter(db, "u1", c.id)
    assert got is not None and got.status == "done" and got.word_count > 0
    assert result["model"] == "mock"


@pytest.mark.anyio
async def test_generate_chapter_no_cards(
    db_session: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.roleplay as rp_mod

    async def _no_cards(db: object, uid: str, ids: list[str]) -> list:
        return []

    monkeypatch.setattr(story_forge.roleplay, "_load_cards", _no_cards)
    monkeypatch.setattr(rp_mod, "_load_cards", _no_cards)
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="T")
    c = await story_forge.create_chapter(db, "u1", p.id)
    result = await story_forge.generate_chapter(db, "u1", p.id, c.id)
    assert result.get("error") and "角色卡" in result["error"]


# ==== 剧本模式生成 ====


@pytest.mark.anyio
async def test_generate_chapter_script(db_session: object, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fakes(monkeypatch, reply="我们出发吧。 [情绪:开心]")
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="晨星山物语")
    c = await story_forge.create_chapter(db, "u1", p.id, title="山顶夜话", outline="山巅对峙")
    result = await story_forge.generate_chapter_script(db, "u1", p.id, c.id, rounds=3)
    assert "error" not in result, result
    assert result["turns"] >= 1
    assert "露娜：" in result["content"] and "洛根：" in result["content"]
    # 情绪标签已清理
    assert "情绪" not in result["content"]
    got = await story_forge.get_chapter(db, "u1", c.id)
    assert got is not None and got.status == "done"


@pytest.mark.anyio
async def test_generate_chapter_script_single_card(
    db_session: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.roleplay as rp_mod

    async def _one_card(db: object, uid: str, ids: list[str]) -> list[tuple[str, dict]]:
        return _fake_cards("露娜")

    monkeypatch.setattr(story_forge.roleplay, "_load_cards", _one_card)
    monkeypatch.setattr(rp_mod, "_load_cards", _one_card)
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="T")
    c = await story_forge.create_chapter(db, "u1", p.id)
    result = await story_forge.generate_chapter_script(db, "u1", p.id, c.id)
    assert result.get("error") and "2 个角色" in result["error"]


# ==== 大纲生成 ====


@pytest.mark.anyio
async def test_generate_outline(db_session: object, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (
        '[{"title": "启程", "outline": "露娜出发前往晨星山"},'
        '{"title": "山腰", "outline": "遭遇黑猫洛根"}]'
    )
    _install_fakes(monkeypatch, reply=payload)
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="晨星山物语", synopsis="冒险")
    result = await story_forge.generate_outline(db, "u1", p.id, chapters=2)
    assert "error" not in result, result
    assert len(result["chapters"]) == 2
    assert result["chapters"][0]["title"] == "启程"
    assert result["chapters"][0]["outline"] == "露娜出发前往晨星山"
    got = await story_forge.get_project(db, "u1", p.id)
    assert got is not None and got.status == "ongoing"


def test_parse_outline_json() -> None:
    ok = story_forge._parse_outline_json('```json\n[{"title": "A", "outline": "x"}]\n```', 5)
    assert ok[0]["title"] == "A"
    assert story_forge._parse_outline_json("纯文本没有数组", 5) == []
    assert story_forge._parse_outline_json("[]", 5) == []
    trimmed = story_forge._parse_outline_json(
        '[{"title": "A", "outline": "1"}, {"title": "B", "outline": "2"}]', 1
    )
    assert len(trimmed) == 1


# ==== 修订 ====


@pytest.mark.anyio
async def test_revise_chapter(db_session: object, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fakes(monkeypatch, reply="修订后的正文。")
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="T")
    c = await story_forge.create_chapter(db, "u1", p.id, title="第一章")
    await story_forge.update_chapter(db, "u1", c.id, {"content": "旧正文"})
    result = await story_forge.revise_chapter(db, "u1", c.id, "加强氛围描写")
    assert "error" not in result, result
    assert result["content"] == "修订后的正文。"
    got = await story_forge.get_chapter(db, "u1", c.id)
    assert got is not None and got.content == "修订后的正文。"
    bad = await story_forge.revise_chapter(db, "u1", c.id, "  ")
    assert "error" in bad


# ==== 导出 ====


@pytest.mark.anyio
async def test_export_markdown_and_jsonl(db_session: object) -> None:
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(
        db, "u1", title="晨星山物语", genre="奇幻", synopsis="冒险"
    )
    c = await story_forge.create_chapter(db, "u1", p.id, title="启程")
    await story_forge.update_chapter(db, "u1", c.id, {"content": "正文第一段"})
    md = await story_forge.export_project(db, "u1", p.id, "markdown")
    assert md["filename"].endswith(".md")
    assert "# 晨星山物语" in md["content"]
    assert "正文第一段" in md["content"]
    jl = await story_forge.export_project(db, "u1", p.id, "jsonl")
    lines = jl["content"].splitlines()
    assert json.loads(lines[0])["type"] == "story"
    assert json.loads(lines[1])["type"] == "chapter"


# ==== 连载调度 ====


@pytest.mark.anyio
async def test_serial_tick_creates_task(
    db_session: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.tasks import story_tasks

    _install_fakes(monkeypatch)
    # tick 内部走 story_tasks 模块的 AsyncSessionLocal：替换为测试库
    monkeypatch.setattr(story_tasks, "AsyncSessionLocal", TestingSessionLocal)
    # .env 已开 USE_CELERY_WORKER=1：测试进程无 redis，调度替换为 no-op
    monkeypatch.setattr(story_tasks, "_dispatch_story", lambda tid: None)
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="连载书")
    s = SerialSchedule(
        project_id=p.id,
        user_id="u1",
        interval_minutes=10,
        next_run_at=datetime.now(UTC) - timedelta(minutes=1),
        status="active",
        mode="narrative",
    )
    db.add(s)
    await db.commit()
    out = await story_tasks._run_serial_tick()
    assert out["created"] >= 1
    task_count = (
        await db.execute(
            select(func.count(GenerationTask.id)).where(GenerationTask.task_type == "chapter")
        )
    ).scalar()
    assert task_count and task_count >= 1
    chapters = await story_forge.list_chapters(db, "u1", p.id)
    assert len(chapters) >= 1
    await db.refresh(s)  # 跨会话修改：显式刷新
    assert s.chapter_count >= 1
    assert s.next_run_at > datetime.now(UTC) - timedelta(minutes=1)


@pytest.mark.anyio
async def test_serial_tick_skips_unfinished(
    db_session: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.tasks import story_tasks

    _install_fakes(monkeypatch)
    monkeypatch.setattr(story_tasks, "AsyncSessionLocal", TestingSessionLocal)
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="连载书")
    await story_forge.create_chapter(db, "u1", p.id, title="未完成章")  # status=outline
    s = SerialSchedule(
        project_id=p.id,
        user_id="u1",
        interval_minutes=10,
        next_run_at=datetime.now(UTC) - timedelta(minutes=1),
        status="active",
        mode="narrative",
    )
    db.add(s)
    await db.commit()
    out = await story_tasks._run_serial_tick()
    assert out["created"] == 0 and out["skipped"] == 1


# ==== 技能工具循环 ====


class _ToolCallProvider:
    """第一轮返回工具调用，第二轮返回正文（模拟真实模型工具循环）。"""

    def __init__(self) -> None:
        self.rounds = 0

    async def generate(self, prompt: str, model: str = "mock", **kw: object) -> object:
        self.rounds += 1

        class _R:
            content: str | None = None
            tool_calls: list[object] | None = None

        r = _R()
        if self.rounds == 1:
            r.tool_calls = [{"id": "t1", "name": "read_bible", "arguments": '{"project_id": "p1"}'}]
        else:
            r.content = "参考了圣经后写出的正文。"
        return r


@pytest.mark.anyio
async def test_chapter_tool_loop(db_session: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """tool_loop=True：模型调用工具 → 结果回填 → 续写正文 → 日志落 notes。"""
    import app.mcp.server as mcp_server
    import app.services.roleplay as rp_mod

    async def _fake_load_cards(db: object, uid: str, ids: list[str]) -> list[tuple[str, dict]]:
        return _fake_cards("露娜")

    async def _fake_resolver(db: object, model: str) -> object:
        class _R:
            provider = _ToolCallProvider()
            model = "mock"

        return _R()

    # 工具执行直接返回（read_bible 内部查库，用测试库）
    monkeypatch.setattr(rp_mod, "_load_cards", _fake_load_cards)
    monkeypatch.setattr(story_forge.roleplay, "_load_cards", _fake_load_cards)
    monkeypatch.setattr(story_forge, "resolve_text_provider", _fake_resolver)
    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", TestingSessionLocal)

    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="工具书")
    c = await story_forge.create_chapter(db, "u1", p.id, title="第一章")
    result = await story_forge.generate_chapter(db, "u1", p.id, c.id, tool_loop=True)
    assert "error" not in result, result
    assert result["tool_calls"] and result["tool_calls"][0]["name"] == "read_bible"
    assert "正文" in result["content"]
    got = await story_forge.get_chapter(db, "u1", c.id)
    assert got is not None
    notes = story_forge._load_json(got.notes, {})
    assert notes.get("tool_calls") and notes["tool_calls"][0]["name"] == "read_bible"


@pytest.mark.anyio
async def test_chapter_tool_loop_plain_model(
    db_session: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不支持工具的模型（无 tool_calls 返回）：tool_loop 退化为普通生成。"""
    import app.services.roleplay as rp_mod

    async def _fake_load_cards(db: object, uid: str, ids: list[str]) -> list[tuple[str, dict]]:
        return _fake_cards("露娜")

    async def _fake_resolver(db: object, model: str) -> object:
        class _R:
            provider = _FakeProvider("直接写好的正文。")
            model = "mock"

        return _R()

    monkeypatch.setattr(rp_mod, "_load_cards", _fake_load_cards)
    monkeypatch.setattr(story_forge.roleplay, "_load_cards", _fake_load_cards)
    monkeypatch.setattr(story_forge, "resolve_text_provider", _fake_resolver)
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="工具书")
    c = await story_forge.create_chapter(db, "u1", p.id, title="第一章")
    result = await story_forge.generate_chapter(db, "u1", p.id, c.id, tool_loop=True)
    assert "error" not in result
    assert result["tool_calls"] == []
    assert result["content"] == "直接写好的正文。"


# ==== 连载失败计数 ====


@pytest.mark.anyio
async def test_serial_tick_fail_count_pauses(
    db_session: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """连续失败 3 次自动暂停调度（防死循环刷失败任务）。"""
    from datetime import UTC, datetime, timedelta

    from app.tasks import story_tasks

    db = db_session  # type: ignore[assignment]
    monkeypatch.setattr(story_tasks, "AsyncSessionLocal", TestingSessionLocal)
    p = await story_forge.create_project(db, "u1", title="连载书")

    async def _boom(db: object, uid: str, pid: str) -> dict[str, Any]:
        raise RuntimeError("上游故障")

    monkeypatch.setattr(story_forge, "create_chapter", _boom)
    s = SerialSchedule(
        project_id=p.id,
        user_id="u1",
        interval_minutes=5,
        next_run_at=datetime.now(UTC) - timedelta(minutes=1),
        status="active",
        mode="narrative",
        fail_count=2,
    )
    db.add(s)
    await db.commit()
    out = await story_tasks._run_serial_tick()
    assert out["created"] == 0
    await db.refresh(s)
    assert s.status == "paused"
    assert "自动暂停" in s.error_message


# ==== 项目统计 ====


@pytest.mark.anyio
async def test_list_projects_stats(db_session: object) -> None:
    """项目列表附带章节数与总字数聚合。"""
    db = db_session  # type: ignore[assignment]
    p = await story_forge.create_project(db, "u1", title="统计书")
    c1 = await story_forge.create_chapter(db, "u1", p.id, title="一")
    await story_forge.update_chapter(db, "u1", c1.id, {"content": "一二三四五"})
    c2 = await story_forge.create_chapter(db, "u1", p.id, title="二")
    await story_forge.update_chapter(db, "u1", c2.id, {"content": "六七八"})
    items = await story_forge.list_projects(db, "u1")
    by_id = {i["id"]: i for i in items}
    assert by_id[p.id]["chapter_count"] == 2, by_id[p.id]
    assert by_id[p.id]["total_words"] == 8
    # 无章节项目
    p2 = await story_forge.create_project(db, "u1", title="空书")
    items = await story_forge.list_projects(db, "u1")
    by_id = {i["id"]: i for i in items}
    assert by_id[p2.id]["chapter_count"] == 0 and by_id[p2.id]["total_words"] == 0
