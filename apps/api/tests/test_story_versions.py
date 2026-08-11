"""章节版本历史测试：修订自动快照 / 列表 / 还原（还原前再快照）。"""

import pytest
from httpx import AsyncClient


async def _create_project_with_chapter(
    client: AsyncClient,
    admin_token: str,
) -> tuple[str, str]:
    h = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post(
        "/api/v1/story/projects",
        json={
            "title": "版本测试书",
            "genre": "测试",
            "synopsis": "用于版本历史测试",
        },
        headers=h,
    )
    pid = r.json()["project"]["id"]
    r = await client.post(
        f"/api/v1/story/projects/{pid}/chapters",
        json={
            "chapter_no": 1,
            "title": "第一章",
            "outline": "测试大纲",
        },
        headers=h,
    )
    cid = r.json()["chapter"]["id"]
    return pid, cid


@pytest.mark.asyncio
async def test_revise_creates_snapshot_and_restore(
    client: AsyncClient,
    admin_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """修订自动快照旧版 → 列表可见 → 还原后内容回到旧版，且还原前也有快照。"""
    # mock provider：按 prompt 中的关键字返回不同正文

    async def fake_resolve(db, model=""):
        from app.providers.base import TextProvider, TextResult
        from app.services.provider_resolver import ResolvedTextProvider

        class Fake(TextProvider):
            async def generate(self, prompt, model="", **kwargs):
                if "修订指令" in prompt and "改成第二版" in prompt:
                    return TextResult(content="这是第二版内容。")
                return TextResult(content="这是第一版内容。")

            async def stream_generate(self, prompt, model="", **kwargs):
                yield "这是第一版内容。"

        return ResolvedTextProvider(Fake(), "fake-model", False, source="fake")

    # story_forge 模块级绑定，patch 模块内名字才生效
    monkeypatch.setattr("app.services.story_forge.resolve_text_provider", fake_resolve)

    pid, cid = await _create_project_with_chapter(client, admin_token)
    h = {"Authorization": f"Bearer {admin_token}"}

    # 项目需要一个角色（占位卡回退），否则 generate 拒绝
    await client.post(
        f"/api/v1/story/projects/{pid}/characters",
        json={
            "name": "测试侦探",
            "role": "protagonist",
            "description": "测试角色",
            "goals": "破案",
            "arc": "成长",
            "current_state": "开始调查",
        },
        headers=h,
    )

    # 首次生成（第一版）
    r = await client.post(
        f"/api/v1/story/chapters/{cid}/generate",
        json={"project_id": pid, "mode": "narrative", "model": "mock"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert "第一版内容" in r.json()["content"]

    # 修订 → 第二版（自动快照第一版）
    r = await client.post(
        f"/api/v1/story/chapters/{cid}/revise",
        params={"instruction": "改成第二版", "model": "mock"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert "第二版内容" in r.json()["content"]

    # 版本列表：应有 1 个快照（第一版）
    r = await client.get(f"/api/v1/story/chapters/{cid}/versions", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    vid = items[0]["id"]

    # 还原到第一版
    r = await client.post(
        f"/api/v1/story/chapters/{cid}/restore",
        params={"version_id": vid},
        headers=h,
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/v1/story/chapters/{cid}", headers=h)
    assert "第一版内容" in r.json()["chapter"]["content"]

    # 还原后再列表：现在有 2 个版本（第一版快照 + 还原前第二版快照）
    r = await client.get(f"/api/v1/story/chapters/{cid}/versions", headers=h)
    assert len(r.json()["items"]) == 2

    # 还原不存在的版本 → 400
    r = await client.post(
        f"/api/v1/story/chapters/{cid}/restore",
        params={"version_id": "no-such-version"},
        headers=h,
    )
    assert r.status_code == 400
