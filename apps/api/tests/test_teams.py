"""批10：Agent 团队协作服务测试（LLM 全 mock，不触网）。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.models.team_run import TeamRun
from app.services import team_service
from tests.conftest import TestingSessionLocal

_PLAN = """```json
{"members": [
  {"name": "策划", "role": "出创意方向", "task": "定主题与结构"},
  {"name": "写手", "role": "产出正文", "task": "按策划写出文案"},
  {"name": "审校", "role": "质量把关", "task": "润色并给终稿"}
]}
```"""


@pytest_asyncio.fixture
async def sqlite_db():
    async with TestingSessionLocal() as s:
        yield s


def _llm_result(content: str) -> Any:
    obj = type("R", (), {})
    inst = obj()
    inst.content = content
    inst.tool_calls = None
    inst.reasoning = ""
    return inst


def _mock_resolver(calls: list[str]):
    """返回 patch 上下文：把每次 LLM 输出记进 calls。"""

    async def fake_generate(prompt, model, **kw):
        calls.append(prompt)
        if "只输出 JSON" in prompt and "members" in prompt:
            return _llm_result(_PLAN)
        if "最终交付报告" in prompt:
            return _llm_result("【最终报告】成果主体……团队配合顺畅。")
        return _llm_result(f"[{len(calls)}号成员产出] 内容……")

    resolved = type("R", (), {})()
    resolved.provider = AsyncMock()
    resolved.provider.generate = AsyncMock(side_effect=fake_generate)
    resolved.model = "mock-model"
    return patch("app.services.team_service.resolve_text_provider", return_value=resolved)


@pytest.mark.asyncio
async def test_team_full_pipeline(sqlite_db) -> None:
    db = sqlite_db
    row = await team_service.start_team_run(db, "u1", "写一首关于秋天的短诗")
    assert row.status == "planning"

    calls: list[str] = []
    with _mock_resolver(calls):
        await team_service.execute_team_run(db, row.id)

    fresh = await team_service.get_run(db, "u1", row.id)
    assert fresh is not None and fresh.status == "done", fresh.error
    assert len(fresh.members) == 3
    assert [s["name"] for s in fresh.steps] == ["策划", "写手", "审校"]
    # 接力可见性：写手的 prompt 里应包含策划的产出
    writer_prompt = next((p for p in calls if "「写手」" in p), "")
    assert "1号成员产出" in writer_prompt or "2号成员产出" in writer_prompt
    assert "最终报告" in fresh.final_report


@pytest.mark.asyncio
async def test_team_bad_plan_marks_failed(sqlite_db) -> None:
    db = sqlite_db
    row = await team_service.start_team_run(db, "u2", "目标X")

    async def bad_gen(prompt, model, **kw):
        return _llm_result("我不会输出 JSON")

    resolved = type("R", (), {})()
    resolved.provider = AsyncMock()
    resolved.provider.generate = AsyncMock(side_effect=bad_gen)
    resolved.model = "m"
    with patch("app.services.team_service.resolve_text_provider", return_value=resolved):
        await team_service.execute_team_run(db, row.id)
    fresh = await team_service.get_run(db, "u2", row.id)
    assert fresh is not None and fresh.status == "failed"
    assert "规划解析失败" in (fresh.error or "")


@pytest.mark.asyncio
async def test_get_run_scoped_by_user(sqlite_db) -> None:
    db = sqlite_db
    row = await team_service.start_team_run(db, "uA", "目标")
    assert await team_service.get_run(db, "uB", row.id) is None
    assert await team_service.get_run(db, "uA", row.id) is not None


@pytest.mark.asyncio
async def test_list_runs_order(sqlite_db) -> None:
    db = sqlite_db
    await team_service.start_team_run(db, "uL", "第一个")
    await team_service.start_team_run(db, "uL", "第二个")
    rows = await team_service.list_runs(db, "uL")
    assert len(rows) >= 2
    # 同秒插入 created_at 相同（DATETIME 秒级），uuid 序不稳定 → 只验集合与用户隔离
    goals = {r.goal for r in rows}
    assert {"第一个", "第二个"} <= goals

@pytest.mark.asyncio
async def test_team_member_failure_skips_not_fails(sqlite_db) -> None:
    """批12 韧性：写手环节上游炸 → 该步标 skipped，团队仍 done 出报告。"""
    db = sqlite_db
    calls: list[str] = []

    async def flaky_generate(prompt, model, **kw):
        calls.append(prompt)
        if "只输出 JSON" in prompt and "members" in prompt:
            return _llm_result(_PLAN)
        if "最终交付报告" in prompt:
            return _llm_result("【最终报告】写手缺席，其余环节已尽力补位。")
        if "按策划写出文案" in prompt:
            raise RuntimeError("429 Rate exceeded")
        return _llm_result(f"[{len(calls)}号成员产出] 内容……")

    resolved = type("R", (), {})()
    resolved.provider = AsyncMock()
    resolved.provider.generate = AsyncMock(side_effect=flaky_generate)
    resolved.model = "mock-model"
    with patch("app.services.team_service.resolve_text_provider", return_value=resolved):
        row = await team_service.start_team_run(db, "uX", "做一份海报文案")
        await team_service.execute_team_run(db, row.id)
        await db.refresh(row)
        fresh = row
    assert fresh.status == "done", (fresh.status, fresh.error)
    steps = fresh.steps or []
    skipped = [s for s in steps if s.get("skipped")]
    assert len(skipped) == 1 and skipped[0]["name"] == "写手"
    assert "已跳过" in fresh.final_report or "写手缺席" in fresh.final_report
