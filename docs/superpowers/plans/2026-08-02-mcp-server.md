# AIGC Studio MCP Server 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 FastMCP 把 AIGC Studio 全能力（生成/查询/管理，12 个工具）暴露为 MCP，支持 stdio（本地 AI 客户端）与 HTTP /mcp（局域网，JWT 认证）双模式。

**Architecture:** FastMCP 实例内嵌 API 进程：工具直连现有 service 层（`create_media_task`、DB 查询、`upstream_status`、`schedule_register_batch`）；`python -m app.mcp` 跑 stdio；FastAPI `mount("/mcp")` 跑 streamable HTTP，外层 middleware 校验 Bearer JWT。

**Tech Stack:** Python 3.14 / mcp SDK（FastMCP）/ FastAPI / SQLAlchemy async / edge-tts。

**验证环境：** 项目无 git，各任务以「测试全绿 + ruff/mypy」为完成标准（跳过 commit 步骤）。

---

## Task 1: 依赖 + FastMCP 骨架 + stdio 入口

**Files:**
- Modify: `apps/api/pyproject.toml`（加 mcp 依赖）
- Create: `apps/api/app/mcp/__init__.py`、`apps/api/app/mcp/server.py`、`apps/api/app/mcp/__main__.py`

- [ ] **Step 1: 加依赖并安装**

`apps/api/pyproject.toml` 的 dependencies 里加：

```toml
"mcp>=1.2.0",
```

安装（本地 venv 供测试）：

```bash
cd apps/api && .venv/Scripts/python.exe -m pip install "mcp>=1.2.0"
```

- [ ] **Step 2: 创建包与骨架**

`apps/api/app/mcp/__init__.py`：

```python
"""MCP 出口：把 AIGC Studio 能力暴露为 MCP 工具（stdio + HTTP 双模式）。"""

from app.mcp.server import mcp

__all__ = ["mcp"]
```

`apps/api/app/mcp/server.py`：

```python
"""FastMCP 实例与工具定义（stdin/stdout 与 /mcp HTTP 共用）。"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("aigc-studio")
```

`apps/api/app/mcp/__main__.py`：

```python
"""python -m app.mcp → stdio 模式（本地 AI 客户端）。"""

from app.mcp.server import mcp

if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 3: 验证 stdio 启动**

Run: `cd apps/api && echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' | .venv/Scripts/python.exe -m app.mcp 2>&1 | head -c 300`
Expected: 输出 JSON-RPC initialize 响应（`{"jsonrpc":"2.0","id":1,...`）

---

## Task 2: 查询工具（7 个）

**Files:**
- Modify: `apps/api/app/mcp/server.py`
- Create: `apps/api/tests/test_mcp_tools.py`

- [ ] **Step 1: 写失败测试**

`apps/api/tests/test_mcp_tools.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -q`
Expected: FAIL（ImportError: `_task_dict` 不存在）

- [ ] **Step 3: 实现查询工具**

`apps/api/app/mcp/server.py` 追加（FastMCP 实例之后）：

```python
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.asset import Asset
from app.models.generation_task import GenerationTask
from app.models.prompt import Prompt

_MAX_POLL_SECONDS = 300


def _task_dict(t: GenerationTask) -> dict[str, Any]:
    return {
        "id": t.id,
        "task_type": t.task_type,
        "status": t.status,
        "progress": t.progress,
        "model": t.model,
        "error": t.error_message or None,
    }


def _summarize_task_result(t: GenerationTask) -> dict[str, Any]:
    """任务终态摘要：主资产 url + comic 封面/格数。"""
    out = _task_dict(t)
    if not t.result:
        return out
    try:
        r = json.loads(t.result)
    except json.JSONDecodeError:
        return out
    out["asset_url"] = r.get("url")
    comic = r.get("comic")
    if isinstance(comic, dict):
        out["title"] = comic.get("title")
        cover = comic.get("cover")
        if isinstance(cover, dict):
            out["cover_url"] = cover.get("url")
        assets = comic.get("assets")
        if isinstance(assets, list):
            out["panel_count"] = len(assets)
    return out


async def _admin_user_id(db: AsyncSession) -> str:
    """stdio 模式默认用户：admin。"""
    from app.models.user import User

    row = (
        await db.execute(
            select(User).where(User.username == settings.INITIAL_ADMIN_USERNAME).limit(1)
        )
    ).scalar_one_or_none()
    return str(row.id) if row else ""


@mcp.tool()
async def list_tasks(
    status: str = "",
    task_type: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """查询任务中心（可按状态/类型过滤）。"""
    async with AsyncSessionLocal() as db:
        stmt = select(GenerationTask).order_by(GenerationTask.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(GenerationTask.status == status)
        if task_type:
            stmt = stmt.where(GenerationTask.task_type == task_type)
        rows = (await db.execute(stmt)).scalars().all()
        return [_task_dict(t) for t in rows]


@mcp.tool()
async def get_task(task_id: str) -> dict[str, Any]:
    """查询单个任务详情（含结果摘要）。"""
    async with AsyncSessionLocal() as db:
        t = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
        if t is None:
            return {"error": f"任务不存在: {task_id}"}
        return _summarize_task_result(t)


@mcp.tool()
async def list_assets(limit: int = 20) -> list[dict[str, Any]]:
    """素材库最近资产列表。"""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(Asset).order_by(Asset.id.desc()).limit(limit))
        ).scalars().all()
        return [
            {
                "asset_id": a.id,
                "filename": a.filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "url": f"/api/v1/assets/{a.id}/content",
                "task_id": a.task_id,
            }
            for a in rows
        ]


@mcp.tool()
async def get_asset(asset_id: str) -> dict[str, Any]:
    """查询素材详情（返回 content 下载路径）。"""
    async with AsyncSessionLocal() as db:
        a = (
            await db.execute(select(Asset).where(Asset.id == asset_id))
        ).scalar_one_or_none()
        if a is None:
            return {"error": f"素材不存在: {asset_id}"}
        return {
            "asset_id": a.id,
            "filename": a.filename,
            "mime_type": a.mime_type,
            "size_bytes": a.size_bytes,
            "url": f"/api/v1/assets/{a.id}/content",
            "task_id": a.task_id,
        }


@mcp.tool()
async def search_prompts(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """检索 prompt 库（标题/内容模糊匹配）。"""
    async with AsyncSessionLocal() as db:
        like = f"%{query}%"
        rows = (
            await db.execute(
                select(Prompt)
                .where(Prompt.title.like(like) | Prompt.content.like(like))
                .limit(limit)
            )
        ).scalars().all()
        return [
            {"id": p.id, "title": p.title, "content": p.content[:500], "type": p.prompt_type}
            for p in rows
        ]


@mcp.tool()
async def get_upstream_status() -> dict[str, Any]:
    """上游状态：grok 账号池 / 注册机 / grok 图片 / cpa。"""
    from app.api.v1.upstream import upstream_status

    async with AsyncSessionLocal() as db:
        return await upstream_status(db)


@mcp.tool()
async def list_workflows() -> list[dict[str, Any]]:
    """workflow 模板列表。"""
    from app.models.workflow import Workflow

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Workflow).limit(50))).scalars().all()
        return [
            {"id": w.id, "name": getattr(w, "name", ""), "description": getattr(w, "description", "")}
            for w in rows
        ]
```

> 注意：`upstream_status` 的签名是 `(db)`；直接调用需传 db。若字段名与 model 不符，实施时按实际 model 调整（`Workflow` 的字段名以 `apps/api/app/models/workflow.py` 为准）。

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/mcp/ tests/test_mcp_tools.py` 与 `-m mypy app/mcp/` → 全过

---

## Task 3: 生成工具（4 个）

**Files:**
- Modify: `apps/api/app/mcp/server.py`
- Modify: `apps/api/tests/test_mcp_tools.py`

- [ ] **Step 1: 写失败测试**

`tests/test_mcp_tools.py` 追加：

```python
@pytest.mark.anyio
async def test_poll_task_until_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """轮询任务到终态；超时返回当前状态。"""
    from app.mcp import server as mcp_server

    calls: dict[str, int] = {}

    class _FakeDB:
        def __init__(self) -> None:
            self.committed = False

        async def __aenter__(self) -> "_FakeDB":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def execute(self, stmt: object) -> object:
            class _Res:
                def scalar_one_or_none(self) -> _FakeTask | None:
                    n = calls.setdefault("n", 0)
                    calls["n"] += 1
                    if n >= 2:
                        return _FakeTask(status="succeeded")
                    return _FakeTask(status="queued", progress=30)

            return _Res()

    async def fake_session() -> _FakeDB:
        return _FakeDB()

    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", fake_session)
    out = await mcp_server._poll_task("t1", timeout_seconds=0.5)
    assert out["status"] == "succeeded"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py::test_poll_task_until_terminal -q`
Expected: FAIL（`_poll_task` 不存在）

- [ ] **Step 3: 实现生成工具**

`apps/api/app/mcp/server.py` 追加：

```python
async def _poll_task(task_id: str, timeout_seconds: float = _MAX_POLL_SECONDS) -> dict[str, Any]:
    """轮询任务到终态（succeeded/failed/cancelled），超时返回当前状态。"""
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while True:
        async with AsyncSessionLocal() as db:
            t = (
                await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
            ).scalar_one_or_none()
            if t is None:
                return {"error": f"任务不存在: {task_id}"}
            if t.status in ("succeeded", "failed", "cancelled"):
                return _summarize_task_result(t)
        if asyncio.get_event_loop().time() >= deadline:
            return _task_dict(t) | {"note": "超时未完成，请稍后用 get_task 查询"}
        await asyncio.sleep(2)


async def _create_and_poll(
    task_type: str,
    model: str,
    params: Any,
    timeout_seconds: float = _MAX_POLL_SECONDS,
) -> dict[str, Any]:
    """创建媒体任务并轮询到终态。"""
    from app.services.generation_service import create_media_task

    async with AsyncSessionLocal() as db:
        user_id = await _admin_user_id(db)
        if not user_id:
            return {"error": "未找到 admin 用户，无法创建任务"}
        task = await create_media_task(
            db, user_id=user_id, task_type=task_type, model=model, params=params
        )
        task_id = task.id
    return await _poll_task(task_id, timeout_seconds)


@mcp.tool()
async def generate_image(prompt: str, model: str = "") -> dict[str, Any]:
    """文生图：grok-imagine-image。返回任务结果（含 asset_url）。"""
    from app.schemas.generation import ImageGenerationRequest

    params = ImageGenerationRequest(prompt=prompt, model=model or "grok-imagine-image")
    return await _create_and_poll("image", params.model, params)


@mcp.tool()
async def generate_comic(
    prompt: str,
    panels: int = 4,
    style: str = "日式漫画",
    characters: str = "",
    layout: str = "grid",
) -> dict[str, Any]:
    """漫画生成：分镜→逐格出图→封面+拼合。返回 title/cover_url/panel_count。"""
    from app.schemas.generation import ComicGenerationRequest

    params = ComicGenerationRequest(
        prompt=prompt,
        panels=panels,
        style=style,
        characters=characters,
        layout=layout,
        model="grok-imagine-image",
    )
    return await _create_and_poll("comic", params.model, params)


@mcp.tool()
async def generate_text(prompt: str, model: str = "") -> dict[str, Any]:
    """文本生成（默认 gpt-oss-120b-medium）。"""
    from app.schemas.generation import TextGenerationRequest

    params = TextGenerationRequest(prompt=prompt, model=model, stream=False)
    return await _create_and_poll("text", params.model, params)


@mcp.tool()
async def synthesize_speech(text: str, voice: str = "default") -> dict[str, Any]:
    """语音合成（edge-tts）。返回音频 asset_url。"""
    from app.schemas.generation import AudioGenerationRequest

    params = AudioGenerationRequest(text=text, voice=voice)
    return await _create_and_poll("audio", params.model, params)
```

> 注意：`ImageGenerationRequest` / `TextGenerationRequest` / `AudioGenerationRequest` 的必填字段以 `apps/api/app/schemas/generation.py` 实际定义为准（如 Image 是否需 size 字段），实施时核对。

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/mcp/ tests/test_mcp_tools.py` 与 `-m mypy app/mcp/` → 全过

---

## Task 4: 管理工具（trigger_register_batch）

**Files:**
- Modify: `apps/api/app/mcp/server.py`
- Modify: `apps/api/tests/test_mcp_tools.py`

- [ ] **Step 1: 写失败测试**

```python
def test_trigger_register_batch_creates_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """触发注册批次：生成 task 记录并调度。"""
    from app.mcp import server as mcp_server

    captured: dict[str, object] = {}

    def fake_schedule(task_id: str, run_count: int = 10) -> None:
        captured["task_id"] = task_id
        captured["run_count"] = run_count

    monkeypatch.setattr(mcp_server, "schedule_register_batch", fake_schedule)
    out = mcp_server.trigger_register_batch(count=5)
    assert out["ok"] is True
    assert captured["run_count"] == 5
    assert "task_id" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py::test_trigger_register_batch_creates_task -q`
Expected: FAIL（工具不存在）

- [ ] **Step 3: 实现**

`apps/api/app/mcp/server.py` 追加：

```python
@mcp.tool()
def trigger_register_batch(count: int = 10) -> dict[str, Any]:
    """触发注册机刷号批次（后台异步执行）。"""
    from app.tasks.register_batch import _create_task_record, schedule_register_batch

    task_id = _create_task_record(count)
    schedule_register_batch(task_id, count)
    return {"ok": True, "task_id": task_id, "run_count": count}
```

> 注意：`_create_task_record` / `schedule_register_batch` 的实际签名以 `apps/api/app/tasks/register_batch.py` 为准（已确认 `schedule_register_batch(task_id, run_count=10)`；`_create_task_record` 返回 task id 字符串）。

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/mcp/ tests/test_mcp_tools.py` 与 `-m mypy app/mcp/` → 全过

---

## Task 5: HTTP 挂载 + JWT 认证

**Files:**
- Modify: `apps/api/app/main.py`
- Create: `apps/api/tests/test_mcp_http.py`

- [ ] **Step 1: 写失败测试**

`apps/api/tests/test_mcp_http.py`：

```python
"""MCP HTTP 端点认证测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_mcp_http_requires_auth() -> None:
    """无 token 访问 /mcp 被拒。"""
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_http.py -q`
Expected: FAIL（当前 /mcp 未挂载 → 404 而非 401/403）

- [ ] **Step 3: 实现挂载 + middleware 认证**

`apps/api/app/main.py` 末尾（`app.include_router(v1_router)` 之后）追加：

```python
# MCP：streamable HTTP 端点（/mcp），外层 JWT 校验
from starlette.middleware.base import BaseHTTPMiddleware

from app.security.auth import get_current_user  # noqa: F401 - 复用 JWT 解析


class _MCPAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
            auth = request.headers.get("authorization", "")
            if not auth.lower().startswith("bearer "):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    {"detail": "MCP 需要 Bearer token"}, status_code=401
                )
            token = auth.split(" ", 1)[1]
            try:
                from app.security.auth import decode_access_token

                payload = decode_access_token(token)
                if not payload or not payload.get("sub"):
                    from fastapi.responses import JSONResponse

                    return JSONResponse({"detail": "token 无效"}, status_code=401)
            except Exception:
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "token 无效"}, status_code=401)
        return await call_next(request)


app.add_middleware(_MCPAuthMiddleware)

from app.mcp.server import mcp  # noqa: E402

app.mount("/mcp", mcp.streamable_http_app())
```

> 注意：`decode_access_token` 的实际函数名/位置以 `apps/api/app/security/auth.py` 为准；若为 `create_access_token`/`decode_token` 等，实施时替换。若 mcp SDK 的 `streamable_http_app` 不接受 mount（需要 path 参数），按其实际 API 调整。

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_http.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/main.py tests/test_mcp_http.py` 与 `-m mypy app/` → 全过

---

## Task 6: 部署 + 真实冒烟 + 文档

**Files:**
- Modify: `docs/mcp-guide.md`（新建）

- [ ] **Step 1: 部署**

```bash
cd D:/software/code/ideas/list/aigc-studio
docker compose build api && docker compose up -d --force-recreate api worker
# 验证：docker ps 显示 api healthy
```

- [ ] **Step 2: HTTP 冒烟**

```bash
# 1) 无 token → 401
curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8002/mcp -H 'Content-Type: application/json' -d '{}'
# 预期 401

# 2) 带 token → MCP initialize 响应（tools/list 列出 12 个工具）
TOKEN=$(curl -s -X POST http://localhost:8002/api/v1/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}' | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
curl -s -X POST http://localhost:8002/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
# 预期 JSON-RPC 响应；随后发 tools/list 确认 12 个工具
```

- [ ] **Step 3: stdio 冒烟（只读工具，零配额消耗）**

```bash
docker exec aigc-studio-api-1 sh -c 'echo "..." | python -m app.mcp'  # initialize + tools/call get_upstream_status
```

- [ ] **Step 4: 真实工具调用**

- `generate_text(prompt="用一句话介绍自己")` → 轮询返回任务结果（含文本内容）
- `search_prompts(query="橘猫")` → 返回匹配 prompt
- `list_tasks(limit=3)` → 最近任务

- [ ] **Step 5: 文档 `docs/mcp-guide.md`**

内容：MCP 是什么（一句话）、工具清单表、Claude Desktop 配置示例（stdio docker exec）、HTTP 用法（curl + JWT）、安全说明（/mcp 需要 Bearer token；远程暴露需公网网关）、常见问题（任务超时用 get_task 查询）。

Claude Desktop 配置示例：

```json
{
  "mcpServers": {
    "aigc-studio": {
      "command": "docker",
      "args": ["exec", "-i", "aigc-studio-api-1", "python", "-m", "app.mcp"]
    }
  }
}
```

- [ ] **Step 6: 回归**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q` → 全绿；上游状态页全绿；10 容器 Up

---

## 自审记录

- 规格覆盖：12 工具（Task 2 查询 7 + Task 3 生成 4 + Task 4 管理 1）✓；stdio（Task 1）✓；HTTP + JWT（Task 5）✓；部署/冒烟/文档（Task 6）✓
- 无占位符 ✓（所有代码步骤完整；`decode_access_token`/`streamable_http_app` 等标注了实施时核对的实际 API）
- 类型一致性：`_task_dict`/`_summarize_task_result`/`_poll_task`/`_create_and_poll` 签名在 Task 2/3 定义并一致使用；`trigger_register_batch(count=5)` 与 `_create_task_record(count)` 一致 ✓
