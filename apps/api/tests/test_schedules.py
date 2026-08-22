"""定时创作（Scheduled Creations）API + 调度扫描测试。

- API：创建/列表/详情/更新/删除/run-now（入队生成任务）
- 调度扫描：run_due_schedules 只处理 is_enabled=1 且到期；禁用后不被调度
- run-now 的 text 任务 mock 掉 LLM（_run_text_task 不真调 provider）
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tests.conftest import TestingSessionLocal


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sched_model():
    from app.models.scheduled_creation import ScheduledCreation

    return ScheduledCreation


async def _create_schedule(
    client, token: str, prompt: str = "每日灵感", **extra
) -> dict:
    payload = {
        "prompt": prompt,
        "task_type": extra.pop("task_type", "text"),
        "schedule_type": extra.pop("schedule_type", "interval"),
        "interval_hours": extra.pop("interval_hours", 6),
        **extra,
    }
    r = await client.post("/api/v1/schedules", headers=_headers(token), json=payload)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _fake_text_runner(monkeypatch):
    """text 任务的执行器替换为假实现（不真调 provider / LLM）。"""
    import app.services.schedule_service as schedule_service

    async def fake_run_text(db, task, prompt):
        task.status = "succeeded"
        task.result = f"【假文本结果】{prompt}"
        task.progress = 100
        await db.commit()

    monkeypatch.setattr(schedule_service, "_run_text_task", fake_run_text)


@pytest.mark.asyncio
async def test_create_interval_computes_next_run_at(client, user_token) -> None:
    """创建 interval 调度：next_run_at ≈ now + interval_hours。"""
    before = datetime.now(UTC)
    data = await _create_schedule(
        client, user_token, schedule_type="interval", interval_hours=6
    )
    after = datetime.now(UTC)
    nxt = datetime.fromisoformat(data["next_run_at"])
    assert data["is_enabled"] is True
    assert nxt > before
    assert nxt >= after + timedelta(hours=6) - timedelta(minutes=1)
    assert nxt <= after + timedelta(hours=6) + timedelta(minutes=1)
    assert data["interval_hours"] == 6
    assert data["daily_time"] is None


@pytest.mark.asyncio
async def test_create_daily_computes_next_run_at(client, user_token) -> None:
    """创建 daily 调度：next_run_at 落在上海时区对应 HH:MM（UTC+8 固定）。"""
    data = await _create_schedule(
        client, user_token, schedule_type="daily", daily_time="09:30"
    )
    nxt = datetime.fromisoformat(data["next_run_at"])
    # 转上海本地（固定 +8）验证小时分钟
    sh = nxt.astimezone(timezone(timedelta(hours=8)))
    assert (sh.hour, sh.minute) == (9, 30)
    assert sh.date() >= datetime.now(UTC).astimezone(timezone(timedelta(hours=8))).date()
    assert data["daily_time"] == "09:30"


@pytest.mark.asyncio
async def test_create_daily_requires_time(client, user_token) -> None:
    """daily 无 daily_time → 400。"""
    r = await client.post(
        "/api/v1/schedules",
        headers=_headers(user_token),
        json={"prompt": "x", "schedule_type": "daily"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_interval_requires_hours(client, user_token) -> None:
    """interval 无 interval_hours → 400。"""
    r = await client.post(
        "/api/v1/schedules",
        headers=_headers(user_token),
        json={"prompt": "x", "schedule_type": "interval"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_requires_auth(client) -> None:
    """未登录 → 401。"""
    r = await client.post(
        "/api/v1/schedules",
        json={"prompt": "x", "schedule_type": "interval", "interval_hours": 1},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_and_get(client, user_token) -> None:
    """列表 + 详情。"""
    s1 = await _create_schedule(client, user_token, "灵感一")
    s2 = await _create_schedule(client, user_token, "灵感二", interval_hours=12)
    r = await client.get("/api/v1/schedules", headers=_headers(user_token))
    assert r.status_code == 200
    items = r.json()["data"]
    assert {i["id"] for i in items} == {s1["id"], s2["id"]}

    r2 = await client.get(f"/api/v1/schedules/{s1['id']}", headers=_headers(user_token))
    assert r2.status_code == 200
    assert r2.json()["data"]["prompt"] == "灵感一"


@pytest.mark.asyncio
async def test_get_other_user_404(client, user_token, admin_token) -> None:
    """他人调度 404；管理员可见。"""
    s = await _create_schedule(client, user_token, "私有调度")
    from app.core.security import hash_password
    from app.models.user import User

    async with TestingSessionLocal() as db:
        db.add(
            User(
                username="sched-user2",
                email="sched-user2@test.local",
                password_hash=hash_password("sched123"),
                role="user",
            )
        )
        await db.commit()
    r2log = await client.post(
        "/api/v1/auth/login", json={"username": "sched-user2", "password": "sched123"}
    )
    other = r2log.json()["access_token"]
    r2 = await client.get(f"/api/v1/schedules/{s['id']}", headers=_headers(other))
    assert r2.status_code == 404
    r3 = await client.get(f"/api/v1/schedules/{s['id']}", headers=_headers(admin_token))
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_update_recomputes_next_run_at(client, user_token) -> None:
    """PUT：改 interval_hours → next_run_at 按新值重算；改 prompt 不动时间。"""
    s = await _create_schedule(
        client, user_token, "旧 prompt", schedule_type="interval", interval_hours=6
    )
    old_next = datetime.fromisoformat(s["next_run_at"])

    # 只改 prompt：时间不变
    r1 = await client.put(
        f"/api/v1/schedules/{s['id']}",
        headers=_headers(user_token),
        json={"prompt": "新 prompt"},
    )
    assert r1.status_code == 200
    d1 = r1.json()["data"]
    assert d1["prompt"] == "新 prompt"
    assert datetime.fromisoformat(d1["next_run_at"]) == old_next

    # 改 interval_hours：重算
    r2 = await client.put(
        f"/api/v1/schedules/{s['id']}",
        headers=_headers(user_token),
        json={"interval_hours": 24},
    )
    d2 = r2.json()["data"]
    new_next = datetime.fromisoformat(d2["next_run_at"])
    assert new_next > old_next
    assert new_next - old_next >= timedelta(hours=18)


@pytest.mark.asyncio
async def test_update_disable_keeps_next_run(client, user_token) -> None:
    """PUT：is_enabled=false 保留配置；下次扫描不再命中。"""
    s = await _create_schedule(client, user_token, "开关调度", interval_hours=1)
    r = await client.put(
        f"/api/v1/schedules/{s['id']}",
        headers=_headers(user_token),
        json={"is_enabled": False},
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["is_enabled"] is False
    assert d["interval_hours"] == 1

    # 禁用后 run_due_schedules 不处理它（即使 next_run_at 已到期）
    import app.services.schedule_service as schedule_service

    async with TestingSessionLocal() as db:
        sched = await db.get(_sched_model(), s["id"])
        sched.next_run_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()
        result = await schedule_service.run_due_schedules(db)
    assert result["ran"] == 0


@pytest.mark.asyncio
async def test_delete(client, user_token) -> None:
    """DELETE：删除后详情 404。"""
    s = await _create_schedule(client, user_token, "待删")
    r = await client.delete(f"/api/v1/schedules/{s['id']}", headers=_headers(user_token))
    assert r.status_code == 200
    r2 = await client.get(f"/api/v1/schedules/{s['id']}", headers=_headers(user_token))
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_run_now_enqueues_task(client, user_token, monkeypatch) -> None:
    """run-now：text 类型 → 创建 GenerationTask 并同步完成，调度记录 last_result_task_id。"""
    _fake_text_runner(monkeypatch)
    s = await _create_schedule(client, user_token, "立即执行", task_type="text")
    r = await client.post(
        f"/api/v1/schedules/{s['id']}/run-now", headers=_headers(user_token)
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["task_id"]
    assert data["task_type"] == "text"
    assert data["status"] == "succeeded"

    from app.models.generation_task import GenerationTask
    from app.models.user import User

    async with TestingSessionLocal() as db:
        task = await db.get(GenerationTask, data["task_id"])
        assert task is not None
        assert task.task_type == "text"
        assert task.status == "succeeded"
        assert "立即执行" in task.result
        u = (await db.execute(select(User).where(User.username == "user1"))).scalar_one()
        assert task.user_id == u.id
        sched = await db.get(_sched_model(), s["id"])
        assert sched.last_result_task_id == data["task_id"]
        assert sched.last_run_at is not None
        assert sched.last_error is None


@pytest.mark.asyncio
async def test_run_now_image_enqueues_queued_task(client, user_token, monkeypatch) -> None:
    """run-now：image 类型 → 复用 create_media_task 入队（queued，不真跑生成）。"""
    import app.services.generation_service as gen_service

    dispatched: list[tuple[str, str]] = []

    def fake_dispatch(task_id: str, task_type: str) -> None:
        dispatched.append((task_id, task_type))

    monkeypatch.setattr(gen_service, "_dispatch", fake_dispatch)

    s = await _create_schedule(client, user_token, "定时出图", task_type="image")
    r = await client.post(
        f"/api/v1/schedules/{s['id']}/run-now", headers=_headers(user_token)
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["task_type"] == "image"
    assert data["status"] == "queued"
    assert dispatched
    assert dispatched[-1] == (data["task_id"], "image")


@pytest.mark.asyncio
async def test_due_schedules_enqueue_and_advance(client, user_token, monkeypatch) -> None:
    """run_due_schedules：到期启用调度 → 入队 + 推进 next_run_at + 记录 last_run_at。"""
    _fake_text_runner(monkeypatch)
    import app.services.schedule_service as schedule_service

    s = await _create_schedule(
        client, user_token, "到期任务", schedule_type="interval", interval_hours=2
    )
    from app.models.generation_task import GenerationTask

    async with TestingSessionLocal() as db:
        sched = await db.get(_sched_model(), s["id"])
        sched.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
        result = await schedule_service.run_due_schedules(db)
        assert result["ran"] == 1
        assert result["due"] == 1
        await db.refresh(sched)
        assert sched.last_run_at is not None
        assert sched.last_result_task_id
        # 推进：下次执行时间在 now 之后
        assert sched.next_run_at > datetime.now(UTC)
        task = await db.get(GenerationTask, sched.last_result_task_id)
        assert task is not None
        assert task.status == "succeeded"


@pytest.mark.asyncio
async def test_disabled_schedule_not_picked_up(client, user_token, monkeypatch) -> None:
    """run_due_schedules：禁用调度即使到期也不被调度（入队数 0）。"""
    _fake_text_runner(monkeypatch)
    import app.services.schedule_service as schedule_service

    s = await _create_schedule(
        client, user_token, "禁用任务", schedule_type="interval", interval_hours=1
    )
    from app.models.generation_task import GenerationTask

    async with TestingSessionLocal() as db:
        sched = await db.get(_sched_model(), s["id"])
        sched.is_enabled = False
        sched.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
        before = (
            await db.execute(select(GenerationTask).where(GenerationTask.user_id == sched.user_id))
        ).scalars().all().__len__()
        result = await schedule_service.run_due_schedules(db)
        assert result["ran"] == 0
        assert result["due"] == 0
        after = (
            await db.execute(select(GenerationTask).where(GenerationTask.user_id == sched.user_id))
        ).scalars().all().__len__()
        assert after == before  # 没有新增任务
        # next_run_at 没有被推进（未命中）
        await db.refresh(sched)
        assert sched.next_run_at <= datetime.now(UTC)
