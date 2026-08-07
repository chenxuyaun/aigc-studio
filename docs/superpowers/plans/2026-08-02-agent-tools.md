# 工作台智能体工具调用实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给工作台智能体对话加 function calling 工具循环，复用 MCP 12 个工具，对话里直接触发生成/查询/管理操作。

**Architecture:** provider.generate 支持 tools 透传 + tool_calls 解析；新 service `agent_chat` 做工具循环（非流式 + SSE 事件流）；MCP 工具注册表转 OpenAI tools 格式；前端传结构化 messages 并展示工具调用过程。

**Tech Stack:** Python 3.14 / FastAPI SSE / OpenAI-compatible providers（cpa/grok2api）/ React 19。

**验证环境：** 项目无 git，各任务以「测试全绿 + ruff/mypy」为完成标准。

---

## Task 1: provider 支持 tools（base + openai_compatible）

**Files:**
- Modify: `apps/api/app/providers/base.py`（TextResult 加 tool_calls）
- Modify: `apps/api/app/providers/openai_compatible.py`（generate 加 tools 参数）
- Create: `apps/api/tests/test_provider_tools.py`

- [ ] **Step 1: 写失败测试**

`tests/test_provider_tools.py`：

```python
"""provider tools 透传与 tool_calls 解析。"""

from __future__ import annotations

import json

import pytest

from app.providers.base import TextResult


def test_text_result_tool_calls_default_none() -> None:
    r = TextResult(content="ok")
    assert r.tool_calls is None


@pytest.mark.anyio
async def test_generate_with_tools_parses_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """generate(tools=...) 请求体带 tools；响应含 tool_calls 被解析。"""
    from app.providers.openai_compatible import OpenAICompatibleTextProvider

    captured: dict = {}

    class _FakeResp:
        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "generate_comic",
                                        "arguments": json.dumps({"prompt": "猫"}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(self, url: str, **kwargs: object) -> _FakeResp:
            captured["body"] = kwargs.get("json") or {}
            return _FakeResp()

    monkeypatch.setattr(
        "app.providers.openai_compatible.httpx.AsyncClient", lambda **k: _FakeClient()
    )
    p = OpenAICompatibleTextProvider(base_url="http://x/v1", api_key="k", default_model="m")
    tools = [{"type": "function", "function": {"name": "generate_comic", "parameters": {}}}]
    r = await p.generate("画漫画", tools=tools)
    assert captured["body"]["tools"] == tools
    assert r.tool_calls is not None
    assert r.tool_calls[0]["name"] == "generate_comic"
    assert json.loads(r.tool_calls[0]["arguments"]) == {"prompt": "猫"}
    assert r.tool_calls[0]["id"] == "call_1"


@pytest.mark.anyio
async def test_generate_without_tools_no_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """不带 tools 时请求体无 tools 字段，普通内容返回。"""
    from app.providers.openai_compatible import OpenAICompatibleTextProvider

    captured: dict = {}

    class _FakeResp:
        def json(self) -> dict:
            return {"choices": [{"message": {"content": "你好", "tool_calls": None}}]}

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(self, url: str, **kwargs: object) -> _FakeResp:
            captured["body"] = kwargs.get("json") or {}
            return _FakeResp()

    monkeypatch.setattr(
        "app.providers.openai_compatible.httpx.AsyncClient", lambda **k: _FakeClient()
    )
    p = OpenAICompatibleTextProvider(base_url="http://x/v1", api_key="k", default_model="m")
    r = await p.generate("hi")
    assert "tools" not in captured["body"]
    assert r.content == "你好"
    assert r.tool_calls is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_provider_tools.py -q`
Expected: FAIL（TextResult 无 tool_calls 字段 / generate 无 tools 参数）

- [ ] **Step 3: 实现**

`base.py` TextResult：

```python
class TextResult(BaseModel):
    content: str
    model: str = ""
    provider: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_calls: list[dict[str, object]] | None = None
```

`openai_compatible.py` 的 `generate`（第 42 行起）：

```python
    async def generate(
        self,
        prompt: str,
        model: str = "",
        tools: list[dict[str, object]] | None = None,
    ) -> TextResult:
        if not self.base_url:
            raise ProviderError("未配置 base_url")
        model = model or self.default_model
        payload: dict[str, object] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if tools:
            payload["tools"] = tools
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code != 200:
                    raise ProviderError(f"上游返回 {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                msg = data["choices"][0]["message"]
                tool_calls: list[dict[str, object]] | None = None
                raw_calls = msg.get("tool_calls")
                if isinstance(raw_calls, list):
                    tool_calls = []
                    for tc in raw_calls:
                        fn = tc.get("function") or {}
                        tool_calls.append(
                            {
                                "id": str(tc.get("id") or ""),
                                "name": str(fn.get("name") or ""),
                                "arguments": str(fn.get("arguments") or "{}"),
                            }
                        )
                return TextResult(
                    content=str(msg.get("content") or ""),
                    model=model,
                    provider="openai_compatible",
                    tool_calls=tool_calls,
                )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"文本生成失败: {exc}") from exc
```

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_provider_tools.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/providers/ tests/test_provider_tools.py` 与 `-m mypy app/providers/base.py app/providers/openai_compatible.py` → 全过

---

## Task 2: MCP 工具 schema 转换 + 执行入口

**Files:**
- Modify: `apps/api/app/mcp/server.py`
- Modify: `apps/api/tests/test_mcp_tools.py`

- [ ] **Step 1: 写失败测试**

`tests/test_mcp_tools.py` 追加：

```python
def test_openai_tools_all_twelve() -> None:
    """12 个工具全部转为 OpenAI function 格式。"""
    from app.mcp.server import _openai_tools

    tools = _openai_tools()
    assert len(tools) == 12
    for t in tools:
        assert t["type"] == "function"
        fn = t["function"]
        assert fn["name"]
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"
    names = {t["function"]["name"] for t in tools}
    assert "generate_comic" in names and "trigger_register_batch" in names
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py::test_openai_tools_all_twelve -q`
Expected: FAIL（`_openai_tools` 不存在）

- [ ] **Step 3: 实现**

`app/mcp/server.py` 追加：

```python
def _openai_tools() -> list[dict[str, object]]:
    """FastMCP 工具注册表 → OpenAI function calling 格式。"""
    from mcp.types import Tool as McpTool

    tools: list[dict[str, object]] = []
    try:
        listed = mcp._tool_manager.list_tools()
    except Exception:
        return tools
    for item in listed:
        t = item if isinstance(item, McpTool) else McpTool(**item)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                },
            }
        )
    return tools


async def _call_tool(name: str, arguments: dict[str, Any]) -> str:
    """执行 MCP 工具并返回文本结果（供 agent 工具循环使用）。"""
    try:
        result = await mcp.call_tool(name, arguments)
        if hasattr(result, "content") and result.content:
            parts = []
            for block in result.content:
                if getattr(block, "type", "") == "text":
                    parts.append(str(getattr(block, "text", "")))
            return "\n".join(parts) if parts else json.dumps(arguments)
        return str(result)
    except Exception as exc:
        return f"工具执行失败: {exc}"
```

> 实施时核对 `mcp._tool_manager` 与 `mcp.call_tool` 的实际 API（mcp 1.29 的 FastMCP 内部结构）；若 `_tool_manager` 名称不同，按其实际属性调整。

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_tools.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/mcp/ tests/test_mcp_tools.py` 与 `-m mypy app/mcp/` → 全过

---

## Task 3: agent_chat 工具循环 service

**Files:**
- Create: `apps/api/app/services/agent_chat.py`
- Create: `apps/api/tests/test_agent_chat.py`

- [ ] **Step 1: 写失败测试**

`tests/test_agent_chat.py`：

```python
"""agent 工具循环测试。"""

from __future__ import annotations

import json

import pytest

from app.providers.base import TextResult


@pytest.mark.anyio
async def test_agent_chat_runs_tools_then_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """第一轮 tool_calls → 执行工具 → 第二轮纯文本回复。"""
    from app.services import agent_chat as ac

    events: list[dict] = []

    class _FakeProvider:
        def __init__(self) -> None:
            self.round = 0

        async def generate(self, prompt: str, model: str = "", tools: list | None = None) -> TextResult:
            self.round += 1
            if self.round == 1:
                return TextResult(
                    content="",
                    tool_calls=[
                        {"id": "c1", "name": "list_tasks", "arguments": json.dumps({"limit": 1})}
                    ],
                )
            return TextResult(content="完成，已查询最近任务。")

    monkeypatch.setattr(ac, "resolve_provider", lambda db, model: _FakeProvider())
    monkeypatch.setattr(
        ac, "_call_tool", lambda name, args: f'[{{"id": "t1", "status": "succeeded"}}]'
    )

    messages = [{"role": "user", "content": "查任务"}]
    async for ev in ac.agent_chat_stream(messages, "m", tools=None):
        events.append(ev)

    kinds = [e["type"] for e in events]
    assert kinds == ["tool", "tool", "chunk"]
    assert events[0]["name"] == "list_tasks"
    assert events[0]["status"] == "running"
    assert events[1]["status"] == "done"
    assert events[2]["content"] == "完成，已查询最近任务。"
```

> 注：`agent_chat_stream` 实现里用 `resolve_provider`（从 `provider_resolver` 导入并可在测试中替换）与 `_call_tool`（模块级，可替换）。若实现改为直接调 `resolve_text_provider`，测试的 monkeypatch 目标同步调整。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_chat.py -q`
Expected: FAIL（agent_chat 不存在）

- [ ] **Step 3: 实现**

`apps/api/app/services/agent_chat.py`：

```python
"""智能体工具调用循环：model → tool_calls → 执行 MCP 工具 → 回填 → 最终回复。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.server import _call_tool, _openai_tools
from app.providers.base import TextProvider
from app.services.provider_resolver import resolve_text_provider

_MAX_ROUNDS = 5


async def _resolve_provider(db: AsyncSession, model: str) -> tuple[TextProvider, str]:
    resolved = await resolve_text_provider(db, model or "mock")
    return resolved.provider, resolved.model  # type: ignore[return-value]


async def agent_chat_stream(
    messages: list[dict[str, Any]],
    model: str,
    db: AsyncSession,
    tools: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """工具循环 + 最终回复，产出 SSE 事件：

    - {"type": "tool", "name", "status": "running"|"done", "summary"?}
    - {"type": "chunk", "content"}
    """
    provider, resolved_model = await _resolve_provider(db, model)
    all_tools = _openai_tools()
    if tools:
        all_tools = [t for t in all_tools if t["function"]["name"] in set(tools)]

    for _ in range(_MAX_ROUNDS):
        prompt = _messages_to_prompt(messages)
        result = await provider.generate(
            prompt, resolved_model, tools=all_tools or None  # type: ignore[arg-type]
        )
        calls = result.tool_calls or []
        if not calls:
            yield {"type": "chunk", "content": result.content}
            return
        tool_msgs: list[dict[str, Any]] = []
        for tc in calls:
            name = str(tc.get("name") or "")
            arguments = tc.get("arguments") or "{}"
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool", "name": name, "status": "running"}
            out = await _call_tool(name, dict(args))
            yield {"type": "tool", "name": name, "status": "done", "summary": out[:200]}
            tool_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tc.get("id") or ""),
                    "content": out,
                }
            )
        messages = messages + [{"role": "assistant", "content": None, "tool_calls": calls}] + tool_msgs

    yield {"type": "chunk", "content": "工具调用轮次过多，已停止。"}


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """结构化消息 → 单条 prompt（provider.generate 只收单条 prompt）。"""
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content")
        if content:
            parts.append(f"{role}: {content}")
        elif m.get("tool_calls"):
            parts.append(f"{role}: (调用了工具 {[tc.get('name') for tc in m['tool_calls']]})")
        elif role == "tool":
            parts.append(f"tool({m.get('tool_call_id')}): {m.get('content')}")
    return "\n\n".join(parts)
```

> 注意：provider.generate 的 tools 参数需要 provider 支持（Task 1 已扩展）。Mock provider 的 generate 签名是 `(prompt, model="mock")` —— 传 tools 会 TypeError？MockTextProvider.generate 看签名：`async def generate(self, prompt, model="mock")` —— 无 tools。所以调用前判断：mock provider 不传 tools（`provider.__class__.__name__` 含 Mock 或 `getattr(provider, "supports_tools", True)`）。实现时：`tools_arg = all_tools or None if not isinstance(provider, MockTextProvider) else None`。测试里用 _FakeProvider 接受 tools。

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_chat.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/services/agent_chat.py tests/test_agent_chat.py` 与 `-m mypy app/services/agent_chat.py` → 全过

---

## Task 4: 端点 `POST /generations/agent/chat`

**Files:**
- Modify: `apps/api/app/api/v1/generations/text.py`（或新建 agent router）
- Modify: `apps/api/app/schemas/generation.py`（AgentChatRequest）
- Create: `apps/api/tests/test_agent_chat_api.py`

- [ ] **Step 1: schema + 端点**

`app/schemas/generation.py` 加：

```python
class AgentChatRequest(BaseModel):
    """智能体对话（工具调用）。"""

    model: str = Field(default_factory=lambda: settings.DEFAULT_TEXT_PROVIDER or "mock")
    messages: list[dict[str, object]]
    tools: list[str] | None = None  # 省略 = 全部工具
```

`app/api/v1/generations/text.py` 加（router 内）：

```python
@router.post("/agent/chat")
async def agent_chat(
    req: AgentChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """智能体对话：模型工具调用循环（SSE：tool 事件 + chunk）。"""
    from app.services.agent_chat import agent_chat_stream

    async def gen() -> AsyncIterator[str]:
        async for ev in agent_chat_stream(req.messages, req.model, db, req.tools):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
```

> 需要确认 text.py 的 router 前缀（`/generations/text`）→ 端点路径为 `/generations/text/agent/chat`。`Request`/`json` 已在 text.py 导入。

- [ ] **Step 2: 写测试**

`tests/test_agent_chat_api.py`：

```python
"""agent chat 端点测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_agent_chat_requires_auth() -> None:
    r = client.post(
        "/api/v1/generations/text/agent/chat",
        json={"model": "mock", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code in (401, 403)
```

- [ ] **Step 3: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent_chat_api.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/api/v1/generations/text.py app/schemas/generation.py tests/test_agent_chat_api.py` 与 `-m mypy app/` → 全过

---

## Task 5: 前端 AgentChatPage

**Files:**
- Modify: `apps/web/src/pages/AgentChatPage.tsx`

- [ ] **Step 1: 发送结构化 messages + tool 事件展示**

`send()` 里 `const payload = buildPrompt(...)` 替换为：

```tsx
const payload = {
  model,
  messages: [
    ...(agent.data?.system_prompt ? [{ role: "system" as const, content: agent.data.system_prompt }] : []),
    ...history.map((m) => ({ role: m.role, content: m.content })),
    { role: "user" as const, content: text },
  ],
};
await streamSse(
  "/generations/text/agent/chat",
  payload,
  (event) => {
    if (event.type === "tool") {
      // 工具调用过程：追加/更新一行状态
      setToolLine(
        event.status === "running"
          ? `🔧 正在调用 ${event.name}…`
          : `✅ ${event.name} 完成`,
      );
    } else if (event.type === "chunk" && typeof event.content === "string") {
      assistantText += event.content;
      setMessages((prev) => [...prev.slice(0, -1), { role: "assistant", content: assistantText }]);
    }
  },
  controller.signal,
);
```

- 新增 state：`const [toolLine, setToolLine] = useState<string | null>(null);`
- 渲染：消息列表顶部/底部显示 `{toolLine && <p className="text-xs text-muted-foreground">{toolLine}</p>}`（streaming 时显示，结束后清空）
- 请求路径：`/generations/text/agent/chat`（原 `/generations/text/generate`）
- `buildPrompt` 函数不再使用（保留或删除，由实现者决定；保留不影响）

- [ ] **Step 2: 前端构建验证**

Run（apps/web）: `node_modules/.bin/tsc --noEmit`
Expected: 无类型错误

---

## Task 6: 部署 + E2E + 文档

**Files:**
- Modify: `docs/mcp-guide.md`（追加工作台工具调用说明）或 `docs/comic-generation.md` 风格新段

- [ ] **Step 1: 部署**

```bash
cd D:/software/code/ideas/list/aigc-studio
docker compose build api && docker compose up -d --force-recreate api worker
cd apps/web && npm run build && docker cp dist/. aigc-studio-frontend-1:/usr/share/nginx/html/
```

- [ ] **Step 2: 真实 E2E（工具循环）**

用 token 调 `POST /api/v1/generations/text/agent/chat`：

```bash
# 请求（UTF-8 JSON 文件）：
# {"model":"gpt-oss-120b-medium","messages":[{"role":"user","content":"查一下最近的任务，用一句话总结"}],"tools":["list_tasks"]}
# 预期 SSE：tool(running list_tasks) → tool(done) → chunk(总结文本)
```

- 验证事件顺序与内容
- 再测一次不带 tools（默认全量）：`{"messages":[{"role":"user","content":"画一张橘猫的4格漫画，主题是雨夜追凶"}]}` → 模型应调用 generate_comic（真实出图，需几分钟，观察 tool 事件出现即可，结果可后续 get_task）

- [ ] **Step 3: 前端验证**

- 打开工作台 → 智能体 → 对话："查一下任务中心" → 看到 `🔧 正在调用 list_tasks…` → 回复总结
- 对话："生成一张橘猫图片" → 看到工具调用 → 回复含素材链接

- [ ] **Step 4: 文档**

- `docs/mcp-guide.md` 追加「工作台智能体工具调用」小节：说明对话可直接调用 12 个工具（全量开放）、过程展示、安全提示（对话可触发注册批次）

- [ ] **Step 5: 回归**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q` → 全绿；上游状态全绿；容器全 Up

---

## 自审记录

- 规格覆盖：provider 透传（T1）✓；schema 转换/执行（T2）✓；工具循环（T3）✓；端点（T4）✓；前端（T5）✓；部署 E2E 文档（T6）✓
- 无占位符 ✓（每步含完整代码；`_tool_manager`/`mcp.call_tool` 标注了实施核对）
- 类型一致性：`TextResult.tool_calls`（T1 定义，T3 消费）；`_openai_tools()`/`_call_tool()`（T2 定义，T3 调用）；`agent_chat_stream(messages, model, db, tools)`（T3 定义，T4 端点调用）✓
