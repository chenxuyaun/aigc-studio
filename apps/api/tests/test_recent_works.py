"""首页最近作品预览端点：GET /generations/recent。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_recent_works_endpoint(client, admin_token):
    """插入几条不同媒体类型的成功任务，验证 /generations/recent 正确返回。"""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.generation_task import GenerationTask
    from app.models.user import User

    # 拿 admin 的 user_id
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
        admin_id = str(row.id) if row else "admin"
        # 插入任务（同一事务批量）
        s.add_all(
            [
                # 成功图片（带 asset_url + prompt）
                GenerationTask(
                    task_type="image",
                    status="succeeded",
                    result='{"url": "/storage/img/1.png", "prompt": "赛博朋克城市"}',
                    user_id=admin_id,
                    model="mock",
                ),
                # 成功漫画（cover_url + panel_count + title）
                GenerationTask(
                    task_type="comic",
                    status="succeeded",
                    result=(
                        '{"comic": {"title": "小漫画", "cover": {"url": "/storage/comic/c1.jpg"}, '
                        '"assets": [1, 2, 3, 4]}}'
                    ),
                    user_id=admin_id,
                    model="mock",
                ),
                # 成功音频
                GenerationTask(
                    task_type="audio",
                    status="succeeded",
                    result='{"url": "/storage/audio/a1.mp3"}',
                    user_id=admin_id,
                    model="mock",
                ),
                # 失败图片（不应返回）
                GenerationTask(
                    task_type="image",
                    status="failed",
                    result='{"url": "/storage/img/bad.png"}',
                    user_id=admin_id,
                    model="mock",
                ),
                # 成功但文本类型（不应返回）
                GenerationTask(
                    task_type="text",
                    status="succeeded",
                    result='{"content": "hello"}',
                    user_id=admin_id,
                    model="mock",
                ),
            ]
        )
        await s.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get("/api/v1/generations/recent", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    # 应返回 3 条媒体（image/comic/audio），text 与 failed 被过滤
    assert len(items) == 3, [i["task_type"] for i in items]
    by_type = {i["task_type"]: i for i in items}
    assert by_type["image"]["asset_url"] == "/storage/img/1.png"
    assert by_type["image"]["prompt"] == "赛博朋克城市"
    assert by_type["comic"]["cover_url"] == "/storage/comic/c1.jpg"
    assert by_type["comic"]["panel_count"] == 4
    assert by_type["comic"]["title"] == "小漫画"
    assert by_type["audio"]["asset_url"] == "/storage/audio/a1.mp3"

    # limit 参数生效
    resp2 = await client.get("/api/v1/generations/recent?limit=2", headers=headers)
    assert len(resp2.json()["items"]) == 2
