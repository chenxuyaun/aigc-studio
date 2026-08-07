"""工作流最小执行：拓扑串联、上游注入、空图/环检测。"""

from __future__ import annotations

import pytest


async def _create_workflow(client, headers, graph) -> str:
    resp = await client.post(
        "/api/v1/workflows/",
        json={
            "name": "测试工作流",
            "description": "",
            "graph": graph,
            "is_public": False,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_run_workflow_sequential(client, admin_token):
    """两条节点串联：下游提示词包含上游输出（Mock 回显验证）。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "prompt",
                "data": {"name": "构思", "promptContent": "构思一个主题"},
            },
            {
                "id": "n2",
                "type": "prompt",
                "data": {"name": "扩写", "promptContent": "扩写以下内容"},
            },
        ],
        "edges": [{"source": "n1", "target": "n2"}],
    }
    wf_id = await _create_workflow(client, headers, graph)

    resp = await client.post(f"/api/v1/workflows/{wf_id}/run", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert set(data["results"]) == {"n1", "n2"}
    # 下游 n2 的 Mock 回显应包含上游 n1 的输出片段
    assert data["results"]["n1"][:8] in data["results"]["n2"]


@pytest.mark.asyncio
async def test_run_workflow_cycle_rejected(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    graph = {
        "nodes": [
            {"id": "a", "type": "prompt", "data": {"name": "A", "promptContent": "x"}},
            {"id": "b", "type": "prompt", "data": {"name": "B", "promptContent": "y"}},
        ],
        "edges": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ],
    }
    wf_id = await _create_workflow(client, headers, graph)
    resp = await client.post(f"/api/v1/workflows/{wf_id}/run", headers=headers)
    assert resp.status_code == 400
    assert "循环" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_run_workflow_empty_rejected(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    wf_id = await _create_workflow(client, headers, {"nodes": [], "edges": []})
    resp = await client.post(f"/api/v1/workflows/{wf_id}/run", headers=headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_run_workflow_requires_view(client, admin_token, user_token):
    """私有工作流：非作者/非管理员不能运行（404 不泄露存在性）。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    graph = {
        "nodes": [{"id": "a", "type": "prompt", "data": {"name": "A", "promptContent": "hi"}}],
        "edges": [],
    }
    wf_id = await _create_workflow(client, headers, graph)
    resp = await client.post(
        f"/api/v1/workflows/{wf_id}/run", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_workflow_story_nodes(client, admin_token):
    """创作节点：chapter_gen 自动创建章节并落库（无角色卡时返回友好错误不 500）。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    # 先建一个创作项目
    r = await client.post(
        "/api/v1/story/projects",
        json={"title": "工作流书", "genre": "奇幻"},
        headers=headers,
    )
    pid = r.json()["project"]["id"]
    graph = {
        "nodes": [
            {
                "id": "s1",
                "type": "chapter_gen",
                "data": {
                    "name": "写第一章",
                    "model": "mock",
                    "params": {"project_id": pid, "instruction": "开场要吸引人"},
                },
            }
        ],
        "edges": [],
    }
    wf_id = await _create_workflow(client, headers, graph)
    resp = await client.post(f"/api/v1/workflows/{wf_id}/run", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "s1" in data["results"]
    # 无角色卡 → 创作节点返回友好错误文本（不抛 500），元信息记录 error
    assert data["story_results"]["s1"].get("error")
    # 章节已自动创建
    r = await client.get(f"/api/v1/story/projects/{pid}/chapters", headers=headers)
    assert len(r.json()["items"]) == 1
    await client.delete(f"/api/v1/story/projects/{pid}", headers=headers)
