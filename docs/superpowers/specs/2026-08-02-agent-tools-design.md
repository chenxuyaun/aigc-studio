# 工作台智能体工具调用设计文档

> 日期：2026-08-02
> 状态：已批准（全量 12 工具开放 + 显示调用过程）
> 背景：工作台智能体对话（AgentChatPage）是纯文本聊天，模型无法在对话中真正
> 触发生成/查询能力。MCP server 已提供 12 个工具函数（`apps/api/app/mcp/server.py`），
> 本设计把它们接入智能体对话（function calling 循环），实现"对话即操作"。

## 目标

在工作台智能体对话里直接调用平台全部能力：
- 说"画一张雨夜橘猫的 4 格漫画" → 真生成，回复里带封面/漫画页链接
- 说"查一下任务进度/素材库/grok 账号池" → 真查询
- 说"刷一波注册号" → 真触发注册批次（全量开放，用户已确认）

## 架构

```
AgentChatPage（前端）
  → POST /generations/agent/chat（结构化 messages + tools）
  → agent_chat 工具循环（非流式）：
      1. provider.generate(messages, tools) → 模型返回 tool_calls?
      2. 有 → 执行工具（复用 MCP 函数）→ SSE 推 tool 事件
              → messages 追加 assistant(tool_calls) + tool(结果) → 回到 1（≤5 轮）
      3. 无 → SSE 推最终文本（chunk 事件）
  → 前端显示 "🔧 正在调用 generate_comic…" + 最终回复
```

### 组件

| 文件 | 职责 |
|---|---|
| `apps/api/app/providers/base.py` | `TextResult` 加 `tool_calls: list[dict] \| None` |
| `apps/api/app/providers/openai_compatible.py` | `generate()` 加 `tools` 参数透传请求体 + 解析 `message.tool_calls` |
| `apps/api/app/services/agent_chat.py`（新） | 工具循环 + SSE 事件流（`agent_chat_stream` async generator） |
| `apps/api/app/api/v1/generations/text.py` | 新端点 `POST /agent/chat` |
| `apps/api/app/mcp/server.py` | `_openai_tools()`：FastMCP 工具 → OpenAI tools 格式；`_call_tool(name, args)` 统一执行 |
| `apps/web/src/pages/AgentChatPage.tsx` | 发送结构化 messages；处理 tool 事件显示过程 |

### 工具 schema 转换

FastMCP 工具注册表 → OpenAI function 格式：

```json
{"type": "function", "function": {"name": "generate_comic", "description": "...", "parameters": {"type": "object", "properties": {...}}}}
```

实现：遍历 `mcp._tool_manager.list_tools()`（Tool 有 name/description/inputSchema）。

### 工具执行

```python
async def _call_tool(name: str, arguments: dict) -> str:
    try:
        result = await mcp.call_tool(name, arguments)  # FastMCP 统一入口
        return 结果文本（JSON）
    except Exception as e:
        return f"工具执行失败: {e}"
```

若 `mcp.call_tool` 不存在，用 `mcp._tool_manager.call_tool`（实施时核对）。

### 工具循环（agent_chat.py）

```python
async def agent_chat_stream(db, model, messages, tools, max_rounds=5):
    # SSE 事件类型：
    #   {"type": "tool", "name": "...", "status": "running"} / {"type": "tool", "name": "...", "status": "done", "summary": "..."}
    #   {"type": "chunk", "content": "..."}  # 最终回复（单条或流式）
    for round in range(max_rounds):
        result = await provider.generate(messages, tools=...)
        if not result.tool_calls:  # 最终回复
            yield chunk(result.content); return
        for tc in result.tool_calls:
            yield tool running 事件
            out = await _call_tool(tc.function.name, json.loads(tc.function.arguments))
            messages.append({"role": "assistant", "content": None, "tool_calls": [...]})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            yield tool done 事件
    yield chunk("工具调用轮次过多，已停止。")
```

### provider 透传

`OpenAICompatibleTextProvider.generate(prompt, model, tools=None)`：
- payload 加 `tools`（非空时）
- 响应解析：`choices[0].message` 的 `content` + `tool_calls` → `TextResult(content, tool_calls=...)`
- `TextResult.tool_calls`：`[{"id", "name", "arguments"}]`（arguments 为 JSON 字符串）

### 端点

`POST /generations/agent/chat`（复用 text router 或新 router）：

```json
请求: {"model": "gpt-oss-120b-medium", "messages": [{"role": "system"|"user"|"assistant", "content": "..."}], "tools": ["generate_comic", ...] 或省略=全部}
响应: text/event-stream（SSE）
```

- `tools` 省略时默认全部 12 个（全量开放）
- mock 模型：无工具能力 → 直接回复（跳过循环）

### 前端（AgentChatPage）

- 发送 payload 改为：
  ```ts
  {model, messages: [{role: "system", content: agent.system_prompt}, ...历史, {role: "user", content: text}]}
  ```
  （不再 buildPrompt 拼单条 prompt —— 工具结果需要结构化消息回填）
- SSE 处理 `tool` 事件：在消息流上方显示一行 `🔧 正在调用 {name}…`（可折叠为"已调用"状态）
- `chunk` 事件追加到 assistant 文本（现状逻辑）

### 安全

- 全量开放（用户确认）：对话可触发注册批次
- 工具事件标注名称，用户可见
- 文档注明：智能体对话具备真实操作能力

## 测试

| 测试 | 内容 |
|---|---|
| provider tools 透传 | mock 响应含 tool_calls → TextResult.tool_calls 解析正确 |
| 工具循环 | mock provider：第一轮 tool_calls → 执行工具（mock）→ 第二轮纯文本 → 事件顺序 tool→chunk |
| schema 转换 | `_openai_tools()` 输出 12 个 OpenAI function 格式 |
| 端点 | SSE 事件顺序 + 认证 |
| 回归 | 全量 pytest + ruff + mypy |

## 边界（本次不做）

- 不做工具结果的富媒体渲染（链接以文本附在回复里）
- 不做并发工具执行（串行，顺序清晰）
- 不做 agent 级工具白名单配置（全量开放，后续可加）
- 不改 MCP server 本身（工具函数复用）
