import pytest


@pytest.mark.asyncio
async def test_text_generate(client, admin_token):
    if admin_token:
        resp = await client.post(
            "/api/v1/generations/text/generate",
            json={"prompt": "hello", "stream": False},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200


async def test_retry_failed_task(client, user_token) -> None:
    """失败任务原地重试：状态重置为 queued 并重新入队；非失败任务拒绝。"""
    from app.models.generation_task import GenerationTask
    from app.models.user import User
    from sqlalchemy import select

    from tests.conftest import TestingSessionLocal

    headers = {"Authorization": f"Bearer {user_token}"}
    async with TestingSessionLocal() as session:
        uid = (await session.execute(select(User.id).where(User.username == "user1"))).scalar_one()
        task = GenerationTask(
            task_type="text",
            status="failed",
            user_id=uid,
            params='{"prompt": "测试"}',
            error_message="上游 500",
        )
        session.add(task)
        await session.commit()
        tid = task.id

    # 重试 → queued（mock 调度，避免后台线程污染其他测试）
    from unittest.mock import patch

    with patch("app.services.generation_service._dispatch") as m_dispatch:
        resp = await client.post(f"/api/v1/tasks/{tid}/retry", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        m_dispatch.assert_called_once_with(tid, "text")

    # 非失败任务拒绝（刚才已入队为 queued）
    resp = await client.post(f"/api/v1/tasks/{tid}/retry", headers=headers)
    assert resp.status_code == 409, resp.text
