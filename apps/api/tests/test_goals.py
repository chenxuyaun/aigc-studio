"""创作目标模式（Goal Mode）API 测试。

参照 test_creation.py 的 fixture/鉴权写法：
- client / user_token / admin_token fixture 来自 conftest（内存 SQLite）
- goal run 不真调 LLM：monkeypatch goal_service.agent_chat_stream（复用 agent 工具循环的入口）
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.conftest import TestingSessionLocal


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_goal(client, token: str, goal_text: str) -> dict:
    r = await client.post(
        "/api/v1/goals", headers=_headers(token), json={"goal_text": goal_text}
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.mark.asyncio
async def test_create_goal_planned(client, user_token) -> None:
    """创建目标：status=planned，返回记录。"""
    data = await _create_goal(client, user_token, "为我的小说画一张封面插图")
    assert data["id"]
    assert data["goal_text"] == "为我的小说画一张封面插图"
    assert data["status"] == "planned"
    assert data["result_summary"] == ""


@pytest.mark.asyncio
async def test_create_goal_requires_auth(client) -> None:
    """未登录 → 401。"""
    r = await client.post("/api/v1/goals", json={"goal_text": "x"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_goals_own_only_desc(client, user_token) -> None:
    """列表：只返回自己的目标，按 created_at 倒序。"""
    from app.models.creation_goal import CreationGoal
    from app.models.user import User

    # 1) API 建一条；2) 直接插一条别人的 + 两条本人（显式 created_at 控制顺序）
    g1 = await _create_goal(client, user_token, "目标一")
    async with TestingSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == "user1"))).scalar_one()
        db.add(
            CreationGoal(
                user_id=u.id,
                goal_text="晚记录",
                status="planned",
                created_at=datetime.now(UTC),
            )
        )
        db.add(
            CreationGoal(
                user_id=u.id,
                goal_text="早记录",
                status="planned",
                created_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        db.add(
            CreationGoal(
                user_id="someone-else",
                goal_text="别人的目标",
                status="planned",
                created_at=datetime.now(UTC) - timedelta(days=5),
            )
        )
        await db.commit()

    r = await client.get("/api/v1/goals", headers=_headers(user_token))
    assert r.status_code == 200
    items = r.json()["data"]
    texts = [i["goal_text"] for i in items]
    ids = [i["id"] for i in items]
    assert g1["id"] in ids
    assert "别人的目标" not in texts
    assert "晚记录" in texts
    assert "早记录" in texts
    # created_at desc：晚记录应在早记录前
    assert texts.index("晚记录") < texts.index("早记录")


@pytest.mark.asyncio
async def test_get_goal_detail(client, user_token, admin_token) -> None:
    """详情：本人可见；他人 404；管理员可见。"""
    data = await _create_goal(client, user_token, "详情目标")
    r = await client.get(f"/api/v1/goals/{data['id']}", headers=_headers(user_token))
    assert r.status_code == 200
    assert r.json()["data"]["goal_text"] == "详情目标"

    # 他人（第二个普通用户）→ 404
    from app.core.security import hash_password
    from app.models.user import User

    async with TestingSessionLocal() as db:
        db.add(
            User(
                username="goal-user2",
                email="goal-user2@test.local",
                password_hash=hash_password("goal123"),
                role="user",
            )
        )
        await db.commit()
    r2log = await client.post(
        "/api/v1/auth/login", json={"username": "goal-user2", "password": "goal123"}
    )
    other_token = r2log.json()["access_token"]
    r2 = await client.get(f"/api/v1/goals/{data['id']}", headers=_headers(other_token))
    assert r2.status_code == 404

    # 管理员 → 200
    r3 = await client.get(f"/api/v1/goals/{data['id']}", headers=_headers(admin_token))
    assert r3.status_code == 200
    assert r3.json()["data"]["id"] == data["id"]


@pytest.mark.asyncio
async def test_run_goal_succeeds_with_mock_agent(client, user_token, monkeypatch) -> None:
    """run：mock agent 工具循环 → 拆解/调工具/总结 → status=succeeded + result_summary。"""
    import app.services.goal_service as goal_service

    seen: dict = {}

    async def fake_stream(messages, model, db, tools=None):
        # 记录构造的系统提示词与目标文本
        seen["messages"] = messages
        yield {"type": "chunk", "content": "执行计划：1) 拆解主题 2) 调生图工具 3) 总结\n"}
        yield {"type": "tool", "name": "generate_image", "status": "running"}
        yield {"type": "tool", "name": "generate_image", "status": "done", "summary": "ok"}
        yield {"type": "chunk", "content": "【成果总结】封面图已生成：assets/cover.png"}

    monkeypatch.setattr(goal_service, "agent_chat_stream", fake_stream)

    data = await _create_goal(client, user_token, "为小说画封面")
    r = await client.post(f"/api/v1/goals/{data['id']}/run", headers=_headers(user_token))
    assert r.status_code == 200
    result = r.json()["data"]
    assert result["status"] == "succeeded"
    assert "封面图已生成" in result["result_summary"]
    assert result["result_summary"].endswith("assets/cover.png")

    # 系统提示词要求拆解 → 逐步调工具 → 总结
    system_msg = next(m for m in seen["messages"] if m.get("role") == "system")
    assert "拆解" in system_msg["content"]
    assert "工具" in system_msg["content"]
    assert "总结" in system_msg["content"]

    # DB 终态
    from app.models.creation_goal import CreationGoal

    async with TestingSessionLocal() as db:
        goal = await db.get(CreationGoal, data["id"])
        assert goal is not None
        assert goal.status == "succeeded"
        assert "封面图已生成" in goal.result_summary


@pytest.mark.asyncio
async def test_run_goal_agent_error_marks_failed(client, user_token, monkeypatch) -> None:
    """run：agent 执行抛异常 → status=failed + result_summary 带失败原因。"""
    import app.services.goal_service as goal_service

    async def broken_stream(messages, model, db, tools=None):
        yield {"type": "chunk", "content": "开始执行"}
        raise RuntimeError("upstream 503")

    monkeypatch.setattr(goal_service, "agent_chat_stream", broken_stream)
    data = await _create_goal(client, user_token, "会失败的目标")
    r = await client.post(f"/api/v1/goals/{data['id']}/run", headers=_headers(user_token))
    assert r.status_code == 200
    result = r.json()["data"]
    assert result["status"] == "failed"
    assert "503" in result["result_summary"]


@pytest.mark.asyncio
async def test_run_goal_timeout_marks_failed(client, user_token, monkeypatch) -> None:
    """run：超时保护 → status=failed（直接调服务层 + 短超时，验证 180s 逻辑）。"""
    import asyncio

    import app.services.goal_service as goal_service

    async def slow_stream(messages, model, db, tools=None):
        yield {"type": "chunk", "content": "开始"}
        await asyncio.sleep(5)  # 远超测试超时

    monkeypatch.setattr(goal_service, "agent_chat_stream", slow_stream)
    from app.models.creation_goal import CreationGoal

    async with TestingSessionLocal() as db:
        goal = CreationGoal(user_id="u-any", goal_text="慢目标", status="planned")
        db.add(goal)
        await db.commit()
        await db.refresh(goal)
        result = await goal_service.run_goal(db, goal, timeout_seconds=0.05)
        assert result.status == "failed"
        assert "超时" in result.result_summary


@pytest.mark.asyncio
async def test_run_goal_rejects_running(client, user_token, monkeypatch) -> None:
    """run：已 running 的目标拒绝重复执行（409）。"""
    import app.services.goal_service as goal_service

    async def fake_stream(messages, model, db, tools=None):
        yield {"type": "chunk", "content": "ok"}

    monkeypatch.setattr(goal_service, "agent_chat_stream", fake_stream)
    data = await _create_goal(client, user_token, "并发目标")
    from app.models.creation_goal import CreationGoal

    async with TestingSessionLocal() as db:
        goal = await db.get(CreationGoal, data["id"])
        goal.status = "running"
        await db.commit()
    r = await client.post(f"/api/v1/goals/{data['id']}/run", headers=_headers(user_token))
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_list_goals_requires_auth(client) -> None:
    """列表未登录 → 401。"""
    r = await client.get("/api/v1/goals")
    assert r.status_code == 401
