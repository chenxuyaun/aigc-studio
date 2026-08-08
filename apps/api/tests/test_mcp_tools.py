# ruff: noqa: PT018

"""MCP 工具测试：任务/资产/prompt 查询与结果摘要。"""

from __future__ import annotations

import pytest
from app.mcp.server import (
    _summarize_task_result,
    _task_dict,
)


class _FakeTask:
    """最小 GenerationTask 替身。"""

    def __init__(
        self,
        task_id: str = "t1",
        task_type: str = "image",
        status: str = "succeeded",
        progress: int = 100,
        model: str = "grok-imagine-image",
        result: str = '{"asset_id": "a1", "url": "/api/v1/assets/a1/content"}',
        error_message: str = "",
    ) -> None:
        self.id = task_id
        self.task_type = task_type
        self.status = status
        self.progress = progress
        self.model = model
        self.result = result
        self.error_message = error_message


def test_task_dict_fields() -> None:
    t = _FakeTask()
    d = _task_dict(t)
    assert d["id"] == "t1"
    assert d["task_type"] == "image"
    assert d["status"] == "succeeded"
    assert d["progress"] == 100
    assert d["model"] == "grok-imagine-image"


def test_summarize_task_result_with_asset() -> None:
    t = _FakeTask()
    s = _summarize_task_result(t)
    assert s["status"] == "succeeded"
    assert s["asset_url"] == "/api/v1/assets/a1/content"


def test_summarize_task_result_comic() -> None:
    t = _FakeTask(
        task_type="comic",
        result=(
            '{"url": "/api/v1/assets/p1/content", "comic": {"title": "雨夜", '
            '"cover": {"asset_id": "c1", "url": "/api/v1/assets/c1/content"}, '
            '"assets": [{"index": 0, "url": "/api/v1/assets/a0/content"}]}}'
        ),
    )
    s = _summarize_task_result(t)
    assert s["title"] == "雨夜"
    assert s["cover_url"] == "/api/v1/assets/c1/content"
    assert s["panel_count"] == 1


def test_summarize_task_result_failed() -> None:
    t = _FakeTask(status="failed", error_message="配额不足", result="")
    s = _summarize_task_result(t)
    assert s["status"] == "failed"
    assert s["error"] == "配额不足"


@pytest.mark.anyio
async def test_poll_task_until_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """轮询任务到终态。"""
    from app.mcp import server as mcp_server

    calls: dict[str, int] = {"n": 0}

    class _FakeDB:
        async def __aenter__(self) -> _FakeDB:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def execute(self, stmt: object) -> object:
            class _Res:
                def scalar_one_or_none(self) -> _FakeTask | None:
                    n = calls["n"]
                    calls["n"] += 1
                    if n >= 2:
                        return _FakeTask(status="succeeded")
                    return _FakeTask(status="queued", progress=30)

            return _Res()

    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", lambda: _FakeDB())
    out = await mcp_server._poll_task("t1", timeout_seconds=5)
    assert out["status"] == "succeeded"


async def test_trigger_register_batch_creates_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """触发注册批次：生成 task 记录并调度（admin 通过，非 admin 拒绝）。"""
    from app.mcp import server as mcp_server

    captured: dict[str, object] = {}

    def fake_schedule(task_id: str, run_count: int = 10) -> None:
        captured["task_id"] = task_id
        captured["run_count"] = run_count

    monkeypatch.setattr(mcp_server, "schedule_register_batch", fake_schedule)
    monkeypatch.setattr(mcp_server, "_create_task_record", lambda count: "reg-123")

    async def _role_admin(_ctx: object) -> str:
        return "admin"

    async def _role_user(_ctx: object) -> str:
        return "user"

    monkeypatch.setattr(mcp_server, "_request_role", _role_admin)
    out = await mcp_server.trigger_register_batch(count=5)
    assert out["ok"] is True
    assert out["task_id"] == "reg-123"
    assert captured["run_count"] == 5
    # 安全：非 admin 一律拒绝（不生成任务、不调度）
    monkeypatch.setattr(mcp_server, "_request_role", _role_user)
    captured.clear()
    out2 = await mcp_server.trigger_register_batch(count=5)
    assert out2.get("ok") is not True
    assert "仅管理员" in str(out2)
    assert captured == {}


def test_openai_tools_all_twelve() -> None:
    """全部工具（含创作工具 + AgentList 检索）转为 OpenAI function 格式。"""
    from app.mcp.server import _openai_tools

    tools = _openai_tools()
    assert len(tools) == 19  # 12 基础 + 4 创作 + 2 AgentList 检索 + 一致性检查
    for t in tools:
        assert t["type"] == "function"
        fn = t["function"]
        assert fn["name"]
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"
    names = {t["function"]["name"] for t in tools}
    assert "generate_comic" in names
    assert "trigger_register_batch" in names
    assert "search_agent_directory" in names
    assert "get_agent_comparison" in names
    assert "check_story_consistency" in names


def test_openai_tools_story_creation_tools() -> None:
    """创作工具（read_bible/write_chapter/update_character_state/list_outline）已注册并可转换。"""
    from app.mcp.server import _openai_tools

    tools = _openai_tools()
    names = {t["function"]["name"] for t in tools}
    for name in ("read_bible", "write_chapter", "update_character_state", "list_outline"):
        assert name in names, f"缺少创作工具 {name}"


@pytest.mark.anyio
async def test_write_chapter_creates_chapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """write_chapter：章节不存在时自动创建并写入正文，已存在则覆盖。"""
    import app.mcp.server as mcp_server
    from app.mcp.server import write_chapter

    from tests.conftest import TestingSessionLocal

    async def fake_admin(db: object) -> str:
        return "u1"

    monkeypatch.setattr(mcp_server, "_admin_user_id", fake_admin)
    # 工具内部走 mcp_server.AsyncSessionLocal：替换为测试库
    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", TestingSessionLocal)
    from app.core.database import Base

    from tests.conftest import _test_engine

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # 幂等建表
    async with TestingSessionLocal() as db:
        from app.services import story_forge

        p = await story_forge.create_project(db, "u1", title="测试书")
        pid = p.id
        out = await write_chapter(pid, 1, "第一章正文", title="启程")
        assert out["ok"] is True
        chapters = await story_forge.list_chapters(db, "u1", pid)
        assert len(chapters) == 1 and chapters[0]["content"] == "第一章正文"
        out2 = await write_chapter(pid, 1, "修订后", title="启程")
        assert out2["ok"] is True
        chapters = await story_forge.list_chapters(db, "u1", pid)
        assert chapters[0]["content"] == "修订后"


@pytest.mark.anyio
async def test_story_mcp_tools_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """read_bible 不存在项目 / update_character_state 不存在角色 → 友好错误。"""
    import app.mcp.server as mcp_server
    from app.mcp.server import read_bible, update_character_state

    from tests.conftest import TestingSessionLocal

    async def fake_admin(db: object) -> str:
        return "u1"

    monkeypatch.setattr(mcp_server, "_admin_user_id", fake_admin)
    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", TestingSessionLocal)
    from app.core.database import Base

    from tests.conftest import _test_engine

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    out = await read_bible("no-such-project")
    assert "error" in out
    out = await update_character_state("p1", "no-such-char", "状态")
    assert "error" in out
