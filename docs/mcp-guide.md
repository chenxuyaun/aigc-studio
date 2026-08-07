# AIGC Studio MCP 接入指南

> 维护：2026-08-02
> AIGC Studio 的能力通过 MCP（Model Context Protocol）暴露，任何支持 MCP 的
> AI 客户端（Claude Desktop、Cursor、Cline 等）都可以直接调用平台的生成与查询能力。

## 一、工具清单（12 个）

### 生成类
| 工具 | 参数 | 说明 |
|---|---|---|
| `generate_image` | prompt, model? | 文生图（grok-imagine-image），返回 asset_url |
| `generate_comic` | prompt, panels?=4, style?=日式漫画, characters?, layout?=grid | 漫画（分镜→逐格→封面+拼合），返回 title/cover_url/panel_count |
| `generate_text` | prompt, model? | 文本生成（gpt-oss-120b-medium），返回内容 |
| `synthesize_speech` | text, voice?=default | edge-tts 语音合成 |

### 查询类
| 工具 | 参数 | 说明 |
|---|---|---|
| `list_tasks` | status?, task_type?, limit?=20 | 任务中心 |
| `get_task` | task_id | 任务详情 + 结果摘要 |
| `list_assets` | limit?=20 | 素材库最近资产 |
| `get_asset` | asset_id | 素材详情 + 下载路径 |
| `search_prompts` | query, limit?=10 | prompt 库模糊检索 |
| `get_upstream_status` | — | grok 池/注册机/grok 图片/cpa 状态 |
| `list_workflows` | — | workflow 模板列表 |

### 管理类
| 工具 | 参数 | 说明 |
|---|---|---|
| `trigger_register_batch` | count?=10 | 触发注册机刷号批次（后台异步） |

## 二、接入方式

### 1. 本地 AI 客户端（stdio，推荐）

在 AI 客户端配置 MCP server（以 Claude Desktop 为例，`claude_desktop_config.json`）：

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

注意：Windows 下 `docker exec -i` 需要 `-i`（保持 stdin）；若客户端环境无法
访问 docker CLI，可改用 HTTP 方式（见下）。

### 2. 局域网 HTTP

端点：`http://<宿主机IP>:8002/mcp/`（注意结尾斜杠）

需要 Bearer token（AIGC 登录 JWT）：

```bash
TOKEN=$(curl -s -X POST http://localhost:8002/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<你的密码>"}' | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

# 客户端连接时带 Authorization 头，例如：
#   mcpServers: { "aigc-studio": { "type": "http", "url": "http://192.168.x.x:8002/mcp/", "headers": { "Authorization": "Bearer <TOKEN>" } } }
```

### 3. 远程（预留）

`/mcp/` 端点可通过公网网关/反代暴露（如 frp、tailscale），
暴露前建议在网关层加 IP 白名单/更强鉴权（当前仅 Bearer JWT）。

## 三、安全说明

- `/mcp/` 所有请求必须带有效 Bearer token（`type=access`），否则 401
- stdio 模式在容器内运行，仅限本机信任客户端使用
- MCP 工具会真实触发生成/注册操作，不要将 token 泄漏给不受信任的客户端

## 四、常见问题

| 现象 | 处理 |
|---|---|
| 生成类工具返回"超时未完成" | 图片/漫画耗时 2-4 分钟，用 `get_task(task_id)` 稍后查询 |
| 任务 status=failed | 用 `get_task` 看 error 字段；多为上游风控/配额（grok 间歇 503） |
| HTTP 连接 404 | 确认 URL 以 `/mcp/` 结尾（尾斜杠） |
| HTTP 连接 401 | token 过期（默认 24h），重新登录获取 |

## 五、工作台智能体工具调用

工作台「智能体」对话已接入同一个 12 工具（**全量开放**）：

- 对话里说"查一下任务/素材/grok 账号池" → 真查询
- "生成一张橘猫图片 / 4 格漫画 / 语音" → 真生成，回复附链接
- "刷一波注册号" → 真触发注册批次（谨慎使用）

实现：`POST /generations/text/agent/chat`（SSE：`tool` 事件显示过程 + `chunk` 最终回复），
工具循环复用 MCP 工具函数（`app/services/agent_chat.py`），模型可多轮链式调用工具。

> 安全提示：智能体对话具备真实操作能力（含注册批次触发），账号权限即操作权限。

## 六、相关文件

| 路径 | 说明 |
|---|---|
| `apps/api/app/mcp/server.py` | FastMCP 实例 + 12 个工具 |
| `apps/api/app/mcp/__main__.py` | stdio 入口（`python -m app.mcp`） |
| `apps/api/app/main.py` | `/mcp` 挂载 + Bearer 校验 middleware + session lifespan |
| `apps/api/tests/test_mcp_tools.py` / `test_mcp_http.py` | 工具与认证测试 |
| `docs/superpowers/specs/2026-08-02-mcp-server-design.md` | 设计文档 |
| `docs/superpowers/plans/2026-08-02-mcp-server.md` | 实施计划 |
