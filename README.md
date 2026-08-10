# AIGC Studio

AI 创作工作台：文本 / 图片 / 视频 / 语音生成，配套提示词库、Agent、技能、工作流、写真摄影与素材管理。

Monorepo：`apps/web`（React 19 + Vite + Module Federation）、`apps/api`（FastAPI + SQLAlchemy async）、`packages/shared-types`。

> 📖 **项目全景**：完整架构/模块/数据/部署/优化记录见 **[docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md)**；
> 接手 AI 引导见 **AGENTS.md**。

## ✨ 功能亮点

- **🎬 创作圆桌**：任何内容领域（音乐/文案/提示词/角色卡/图片/视频/漫画）都能开一场"定制阵容 → 逐轮真讨论（SSE 实时）→ 批评必须带替代方案 → 主编把关定稿"的创作会议；定稿自带结构自检（空洞赞颂词/唱感均衡/押韵偷懒/段落纪律），严重问题自动重写一轮
- **📚 会生长的知识库**：素材入库即由 AI 提炼「精华解读」（核心意象/主题内核/可化用点/化用禁忌）；创作时自动检索注入；**好作品的定稿自动回填知识库**成为后续创作的营养（创作范例）；联网搜索兜底（SearXNG → Wikipedia，先提炼后注入，素材不劫持主题方向）
- **✍️ 人民性创作信条**：写人先立人（开放主题先立具体人物原型）、叙事铁律（一段一景/戏剧时刻）、落地铁律（拒绝抽象空转）——每一场圆桌都执行
- **🎵 音乐创作**：写歌 / 1对1 讨论室 / 多角色圆桌三档；定稿自动打标签（风格/主题/情感）存入作品库，支持搜索、按标签浏览、对比、匿名分享、发布到创作群
- **🤖 角色陪伴记忆**：原创蒸馏 + MemoryCore 多层记忆（L0-L3），对话注入原著档案与回忆
- **💬 创作群聊**：群内 `@AI 写歌`、`@AI 导演` 指令，直接在群内共创
- **🧩 提示词库治理**：content_hash 去重、垃圾清理、主题检索
- **🛡 开源友好**：`.env` 密钥隔离、生产拒绝默认密钥、私有媒体鉴权访问、AgentList 目录可一键产出 Agent 配置

## 快速开始

```bash
# 1. 安装依赖
pnpm install

# 2. 后端（Python ≥3.14，建议 uv）
cd apps/api
uv venv .venv && source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
uv pip install -e .
alembic upgrade head          # 建表
python -m seed_data           # 首次种子（默认管理员 admin/admin123）
uvicorn app.main:app --port 8001 --reload

# 3. 前端（另开终端）
cd apps/web
pnpm dev                      # http://localhost:5180
```

## 环境变量

复制 `.env.example` 为 `.env` 后按需修改，关键项：

| 变量 | 说明 |
| --- | --- |
| `APP_ENV` | `development` / `production`。生产环境拒绝默认密钥（`JWT_SECRET_KEY` 等必须配置强随机值） |
| `JWT_SECRET_KEY` / `APP_SECRET_KEY` | JWT 与敏感配置加密密钥，生产必须改 |
| `DATABASE_URL` | 默认 SQLite（`apps/api/aigc_studio.db`）；生产可配 MySQL |
| `STORAGE_PROVIDER` | `local`（默认）/ `r2` |
| `OPENAI_COMPATIBLE_*` | OpenAI 兼容网关（如本地 grok2api），文本/图像真实生成 |
| `HUGGINGFACE_TOKEN` | HuggingFace 推理 API（可选） |
| `RATE_LIMIT_PER_MINUTE` | 全局限流（0=关闭）；部署在受信代理后置 `TRUST_PROXY=true` |

## 常用命令

```bash
make test        # 后端 pytest + 前端 vitest
make lint        # ruff + eslint
make migrate     # alembic upgrade head
make seed        # 种子数据
```

## 部署

- **compose 全栈**：`docker compose up -d`（前端 + API + MySQL + Redis + worker）
- **systemd 混合**（服务器）：`bash deploy/scripts/deploy_remote.sh`，详见 `docs/` 规划
- **备份**：`deploy/scripts/backup.sh`（每日 03:30 由 `deploy/systemd/aigc-backup.timer` 触发）

生产部署要点：
1. `.env` 配置强随机 `JWT_SECRET_KEY` / `APP_SECRET_KEY`，修改初始管理员密码
2. nginx 已移除 `/storage/` 公开直出——私有媒体统一走鉴权接口
3. 建议启用 TLS（443 + 证书），当前配置为 HTTP

## 模型接入

- **Mock**：离线占位（默认），无需任何 Key
- **Grok**：本地 grok2api（`OPENAI_COMPATIBLE_BASE_URL=http://127.0.0.1:8000/v1`），真实文本 + 图像生成
- **HuggingFace**：免费推理 API（需外网 / Token）

## 运维

- 生成任务/Provider 调用日志：管理端「运行日志」（`/settings/logs`）
- 进程崩溃后遗留任务会在下次启动时自动标记失败（`_recover_stale_tasks`）
