# SillyTavern 接入设计文档

> 日期：2026-08-02
> 状态：已批准（网关 + 角色卡工厂，不动 SillyTavern 源码）
> 背景：用户将 SillyTavern 完整源码（AGPL-3.0）放入项目根目录 `./SillyTavern/`（274MB，含官方 Dockerfile）。
> SillyTavern 是 LLM 角色扮演聊天前端，与 AIGC Studio 创作能力互补。

## 目标

1. **OpenAI 兼容网关**：AIGC 暴露 `/v1/chat/completions`，聚合 Grok（grok2api :8000）与 cpa（:8317）双模型，SillyTavern 配一个地址即可切换
2. **角色卡工厂**：输入角色描述 → cpa 生成角色设定 → grok 生成头像 → 打包 SillyTavern 兼容 PNG 角色卡 → 存素材库
3. **部署**：SillyTavern 容器化入 compose（:8001，restart 自愈，data 卷持久化）+ 工作台入口
4. **文档**：配置指南

## 架构

```
SillyTavern（容器 :8001）
  ├─ OpenAI 兼容 API → AIGC 网关 POST /v1/chat/completions（Bearer JWT）
  │     ├─ model=grok-chat-fast → grok2api（host.docker.internal:8000/v1）
  │     └─ model=gpt-oss-120b-medium → cpa（host.docker.internal:8317/v1）
  └─ 角色卡（PNG tEXt 内嵌 chara JSON，拖入即用）← AIGC 角色卡工厂 → 素材库
```

## 组件

### 1. OpenAI 兼容网关（apps/api/app/api/v1/openai_gateway.py 新 router）

- `POST /v1/chat/completions`，OpenAI 请求格式：`{model, messages, temperature?, max_tokens?, stream?}`
- 鉴权：Bearer AIGC JWT（复用 `get_current_user`；SillyTavern 配置里填 AIGC 登录 token）
- 路由：`model.startswith("grok")` → grok2api 实例；`model.startswith("gpt-oss")` 或其他 → cpa 实例（两个 `OpenAICompatibleTextProvider` 构造，base_url/key 从 DB `_provider_settings` 解析，复用现有函数）
- stream=true → SSE（`data: {...}\n\n` OpenAI 流式格式，SillyTavern 解析标准流）
- 非流式 → OpenAI 标准响应 `{id, object, created, model, choices: [{message: {role, content}}]}` 
- 上游失败 → OpenAI 风格错误 `{"error": {"message", "type", "code"}}` + 合适状态码
- 使用 `_story_api_key`/`_provider_settings` 获取 cpa key；grok key 用 `_grok_image_key`（env/.env）

### 2. 角色卡工厂（apps/api/app/services/character_card.py 新 service + 新 router）

- `POST /api/v1/character-cards/generate`：`{description: str, style?: str = "动漫"}`（JWT 鉴权）
- 流程：
  1. cpa 生成角色卡 V2 JSON（system prompt 严格 JSON）：`{name, description, personality, scenario, first_mes, mes_example}`（宽松解析 + 兜底）
  2. grok 生成头像：`文生图（角色头像，{description}，{style}，竖版半身像）`
  3. PIL 合成 PNG 角色卡：头像图 + `tEXt` 块 `chara` = base64(角色卡 JSON)（SillyTavern V2 标准）
  4. 存素材库（Asset，mime image/png，filename `character-{id}.png`）
- 失败兜底：cpa 失败 → 模板默认角色卡；grok 失败 → 纯色底头像
- 响应：`{task_id, asset_id, url, character: {...}}`（任务化：复用 create_media_task？角色卡是同步生成（chat + 图片 ~1min）→ 直接任务化（type=character_card，走 task_runner？task_runner 不认识该类型。简化：同步端点 + 轮询前端？或复用 media task 机制。
  决定：**同步端点**（cpa chat ~10s + grok 图 ~30s + PIL 合成 ~1s → 总 <1min，前端 loading 即可；不做任务化，避免动 task_runner）
- 前端 `CharacterCardPage`（/create/character-card）：描述 + 风格表单 → 生成（loading）→ 角色卡预览（头像 + 设定字段展示）+ 下载按钮

### 3. 部署（compose.yaml）

```yaml
  sillytavern:
    build:
      context: ./SillyTavern
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "8001:8000"
    volumes:
      - sillytavern_data:/home/node/app/data
    environment:
      - TZ=Asia/Shanghai
```
- 注意：SillyTavern 官方 Dockerfile 默认 CMD 启动 node server；data 卷持久化角色卡/对话/世界书
- 工作台导航加「角色扮演」（AppShell NAV + 新窗口打开 `http://localhost:8001`）

### 4. 文档 docs/sillytavern-guide.md

- 首次配置：右上设置 → API → Custom(OpenAI) → Chat Completion 源 `http://host.docker.internal:8002/v1`，API Key = AIGC 登录 token，模型 `grok-chat-fast` / `gpt-oss-120b-medium` 切换
- 角色卡导入：拖入 PNG 到角色卡管理
- 与 AIGC 分工说明（对话/世界书本地；生成能力走 AIGC）

## 测试

| 测试 | 内容 |
|---|---|
| 网关路由 | mock provider：model 前缀 → 正确上游；未登录 401 |
| 网关格式 | 非流式 OpenAI 响应结构；流式 SSE 事件格式 |
| 角色卡 JSON | mock cpa → 宽松解析 + 兜底 |
| 角色卡 PNG | PIL 合成 → tEXt 块回读 → base64 解码 == 原 JSON |
| 真实冒烟 | 网关 chat（cpa）；角色卡生成（真实 cpa+grok）→ PNG 解析验证 |
| 回归 | 全量 pytest + ruff + mypy + 前端 tsc |

## 边界（本次不做）

- 不动 SillyTavern 源码（对话/世界书存其本地 data 卷）
- 网关不含图片生成（SillyTavern 图片扩展可直连 grok2api）
- 角色卡 MVP：单角色卡 V2，无表情差分/多头像/世界书生成
- 对话记录不同步 AIGC
