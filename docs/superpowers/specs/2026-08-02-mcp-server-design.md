# AIGC Studio MCP Server 设计文档

> 日期：2026-08-02
> 状态：已批准（本地 AI 客户端 stdio + 局域网 HTTP + 远程预留，全能力工具）
> 背景：平台功能众多（图片/漫画/文本/语音/视频/素材库/任务中心/prompt 库/上游状态/注册机），
> 全部锁在自家 REST API 内，外部 AI 助手无法调用。本项目当前无任何 MCP 代码/依赖。

## 目标

把 AIGC Studio 全能力暴露为 MCP（Model Context Protocol）工具，
支持三种接入方式：
1. **本地 AI 客户端**（Claude Desktop / Cursor 等）：stdio 模式
2. **局域网 HTTP**：streamable HTTP 端点（挂到现有 API）
3. **远程预留**：HTTP 端点天然可被公网代理暴露（安全加固留待真正暴露时）

## 架构

```
┌─ 本地 AI 客户端 ──stdio（docker exec python -m app.mcp）──┐
┌─ 局域网设备 ──HTTP /mcp（Bearer JWT）────────────────────┼──→ FastMCP（内嵌 API 进程）
┌─ 远程（预留，公网代理）──────────────────────────────────┘        │
                                                                     ↓
                                              复用现有 service 层
                              create_media_task / comic_service / DB 查询
```

### 组件

| 文件 | 职责 |
|---|---|
| `apps/api/app/mcp/__init__.py` | 包（导出 FastMCP 实例） |
| `apps/api/app/mcp/server.py` | FastMCP("aigc-studio") + 全部工具定义 |
| `apps/api/app/mcp/__main__.py` | `python -m app.mcp` → stdio 入口 |
| `apps/api/app/main.py` | `app.mount("/mcp", streamable_http_app())` |
| `apps/api/pyproject.toml` | 加 `mcp` 依赖 |

### 工具 → service 复用

- 生成类工具调 `generation_service.create_media_task(db, user_id, task_type, model, params)`（异步调度，返回任务 id）
- 查询类工具直接 DB（select GenerationTask / Asset / Prompt）
- 上游状态复用 `upstream.py` 探测逻辑
- 注册批次复用 `register_batch.schedule_register_batch`
- MCP 工具返回结构化 JSON（任务 id/状态/资产信息），生成类工具轮询任务到终态返回结果摘要

### 用户身份

- **stdio**：容器内直连 service，默认 admin 用户（查 DB 取 admin.id）
- **HTTP**：Bearer JWT → 解析用户 id（现有 `get_current_user` 逻辑复用）；未带 token 拒绝

## 工具清单（12 个）

| 类别 | 工具 | 说明 |
|---|---|---|
| 生成 | `generate_image(prompt, model?)` | 文生图，返回 asset url |
| | `generate_comic(prompt, panels?, style?, characters?, layout?)` | 漫画（封面+内容页+分镜），返回 assets |
| | `generate_text(prompt, model?)` | 文本生成 |
| | `synthesize_speech(text, voice?)` | edge-tts 语音 |
| 查询 | `list_tasks(status?, task_type?, limit?)` | 任务中心 |
| | `get_task(task_id)` | 任务详情（含 result） |
| | `list_assets(limit?)` | 素材库 |
| | `get_asset(asset_id)` | 素材信息 + content url |
| | `search_prompts(query, limit?)` | prompt 库检索（模板变量展开前的原文） |
| | `get_upstream_status()` | grok 池/注册机/grok 图片/cpa 状态 |
| 管理 | `trigger_register_batch(count?)` | 触发注册机批次（生成 task 记录） |
| | `list_workflows()` | workflow 模板列表 |

## 认证与安全

- HTTP `/mcp` 端点：FastAPI 层前置校验（middleware 读 `Authorization: Bearer`，用现有 JWT 校验，无效拒绝）—— 实施时优先用 mcp SDK 自带 auth 钩子，SDK 不支持则 middleware
- stdio 模式：容器内本地进程，信任环境
- 远程预留：不改代码，文档注明暴露前需加公网网关/白名单

## 测试

- 单元：mock DB/service，验证工具入参解析与返回结构
- 集成：stdio 模式启动 → 调 `get_upstream_status` / `search_prompts` / `generate_text`（低配额消耗）
- HTTP：`curl /mcp` 冒烟（MCP 协议握手）
- 回归：全量 pytest + 上游状态

## 部署

1. `apps/api/pyproject.toml` 加 `mcp>=1.2.0` → `docker compose build api` + recreate
2. 文档 `docs/mcp-guide.md`：Claude Desktop 配置示例、工具列表、HTTP 用法

## 边界（本次不做）

- 不做 MCP 资源（resources）/提示词（prompts）类型，只做工具（tools）
- 不做远程公网暴露的安全加固（仅预留端点）
- 不做流式输出（SSE 工具进度）—— 生成类工具阻塞轮询返回
- 视频生成：路由存在但当前无真实 provider，不暴露（工具列表后续补）
