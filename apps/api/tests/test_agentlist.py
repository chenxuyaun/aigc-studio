"""AgentList 目录接入测试：解析器单测 + sync 幂等 + API 端点。"""

import pytest
from app.services import agentlist_ingest
from app.services.agentlist_ingest import parse_full_text
from httpx import AsyncClient

MINI_DUMP = """# AgentList — Full Content

## 1. PK Comparison Board

### LangChain vs CrewAI: AI Agent Framework Comparison

- URL: https://www.agentlist.top/en/compare/langchain-vs-crewai/
- Description: Compare LangChain and CrewAI across agent orchestration.
- Categories: agent-framework, multi-agent
- Projects compared: LangChain vs CrewAI

#### Comparison dimensions

| Dimension | LangChain | CrewAI |
|---|---|---|
| Core positioning | General | Multi-agent |

## 2. Long-form Articles

### AutoGPT Alternatives in 2026

- URL: https://www.agentlist.top/en/articles/autogpt-alternatives/
- Description: Why alternatives exist.
- Categories: agent-framework
- Related projects: significant-gravitas-autogpt, all-hands-ai-openhands

# AutoGPT Alternatives in 2026

## 1. Core Problems

Body text here with a ### not-an-entry subsection that must not be split.

### MetaGPT Simulating a Team

- URL: https://www.agentlist.top/en/articles/metagpt-team/
- Description: Team simulation.
- Categories: multi-agent
- Related projects: foundationagents-metagpt

# MetaGPT

## 3. Project Index

### OpenClaw

- URL: https://www.agentlist.top/en/projects/openclaw/
- GitHub: https://github.com/openclaw/openclaw
- Homepage: https://openclaw.org/
- Description: Personal AI assistant platform.
- Categories: Agent Tools
- Tags: assistant, multi-channel
- GitHub stars: 385,143
- Language: TypeScript
- License: Apache-2.0

### Superpowers

- URL: https://www.agentlist.top/en/projects/superpowers/
- GitHub: https://github.com/obra/superpowers
- Description: Claude Code skills.
- Categories: Coding Agent
- Tags: claude-code, skills
- GitHub stars: 266,495
- Language: TypeScript
- License: MIT

## End of dump
"""


# ==== 解析器 ====

def test_parse_full_text_counts() -> None:
    parsed = parse_full_text(MINI_DUMP)
    assert len(parsed["comparisons"]) == 1
    assert len(parsed["articles"]) == 2
    assert len(parsed["projects"]) == 2


def test_parse_project_fields() -> None:
    parsed = parse_full_text(MINI_DUMP)
    p = next(x for x in parsed["projects"] if x["name"] == "OpenClaw")
    assert p["stars"] == 385143  # 千分位逗号
    assert p["language"] == "TypeScript"
    assert p["license"] == "Apache-2.0"
    assert p["github_url"] == "https://github.com/openclaw/openclaw"
    assert "Agent Tools" in __import__("json").loads(p["categories"])
    assert "multi-channel" in __import__("json").loads(p["tags"])


def test_parse_comparison_fields() -> None:
    parsed = parse_full_text(MINI_DUMP)
    c = parsed["comparisons"][0]
    assert c["projects"] == '["LangChain vs CrewAI"]'
    assert "Comparison dimensions" in c["content"]


def test_parse_article_content_not_split_by_inner_headings() -> None:
    parsed = parse_full_text(MINI_DUMP)
    a = next(x for x in parsed["articles"] if "AutoGPT" in x["title"])
    # 正文里 "### not-an-entry" 不应被切成新条目
    assert "not-an-entry" in a["content"]
    assert a["related_projects"] == '["significant-gravitas-autogpt", "all-hands-ai-openhands"]'


def test_parse_ignores_non_entries() -> None:
    """无 GitHub 的块不算项目；无 URL 的块不算文章/对比。"""
    parsed = parse_full_text(MINI_DUMP)
    assert all(p["name"] != "3.1 Featured projects" for p in parsed["projects"])
    assert all(a["title"] != "not-an-entry" for a in parsed["articles"])


# ==== sync 幂等 ====

@pytest.mark.asyncio
async def test_sync_idempotent(
    client: AsyncClient, admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch() -> str:
        return MINI_DUMP

    monkeypatch.setattr(agentlist_ingest, "fetch_full_text", fake_fetch)
    h = {"Authorization": f"Bearer {admin_token}"}
    for _ in range(2):
        r = await client.post("/api/v1/agentlist/sync", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["projects"] == 2
        assert body["articles"] == 2
        assert body["comparisons"] == 1
    r = await client.get("/api/v1/agentlist/stats", headers=h)
    assert r.json()["counts"] == {"projects": 2, "articles": 2, "comparisons": 1}


# ==== API ====

@pytest.mark.asyncio
async def test_api_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/api/v1/agentlist/stats")
    assert r.status_code == 401
    r = await client.get("/api/v1/agentlist/projects")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_list_search_sort(
    client: AsyncClient, admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch() -> str:
        return MINI_DUMP

    monkeypatch.setattr(agentlist_ingest, "fetch_full_text", fake_fetch)
    await client.post("/api/v1/agentlist/sync", headers={"Authorization": f"Bearer {admin_token}"})

    h = {"Authorization": f"Bearer {admin_token}"}
    # 默认按星数排序
    r = await client.get("/api/v1/agentlist/projects", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["items"][0]["name"] == "OpenClaw"  # 385k > 266k

    # 搜索
    r = await client.get("/api/v1/agentlist/projects?search=super", headers=h)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["name"] == "Superpowers"

    # 分类过滤
    r = await client.get("/api/v1/agentlist/projects?category=Coding%20Agent", headers=h)
    assert r.json()["total"] == 1

    # 语言过滤
    r = await client.get("/api/v1/agentlist/projects?language=TypeScript", headers=h)
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_api_stats_and_articles(
    client: AsyncClient, admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch() -> str:
        return MINI_DUMP

    monkeypatch.setattr(agentlist_ingest, "fetch_full_text", fake_fetch)
    await client.post("/api/v1/agentlist/sync", headers={"Authorization": f"Bearer {admin_token}"})

    h = {"Authorization": f"Bearer {admin_token}"}
    r = await client.get("/api/v1/agentlist/stats", headers=h)
    body = r.json()
    assert body["counts"] == {"projects": 2, "articles": 2, "comparisons": 1}
    assert ("Agent Tools", 1) in [tuple(x) for x in body["top_categories"]]

    r = await client.get("/api/v1/agentlist/articles", headers=h)
    assert r.json()["total"] == 2

    r = await client.get("/api/v1/agentlist/comparisons", headers=h)
    assert r.json()["total"] == 1
    cid = r.json()["items"][0]["id"]
    r = await client.get(f"/api/v1/agentlist/comparisons/{cid}", headers=h)
    assert "Comparison dimensions" in r.json()["comparison"]["content"]


@pytest.mark.asyncio
async def test_api_sync_requires_admin(
    client: AsyncClient, user_token: str
) -> None:
    r = await client.post(
        "/api/v1/agentlist/sync", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert r.status_code == 403
