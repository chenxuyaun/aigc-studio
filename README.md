# SAIOS — Symbiotic AI OS（共生智能操作系统）

> 原名 AIGC Studio。个人 AI 生命体平台：理解你的目标 → 自主规划 → 调用工具 → 学习成长 → 长期协作。
> 你告诉它"想做什么"，它把 12 个创作引擎融合成一支会自己分工、复盘、进化的 Agent 团队。

Monorepo：`apps/web`（React 19 + Vite + Module Federation + PWA）、`apps/api`（FastAPI + SQLAlchemy async + Celery）、`packages/shared-types`。

> 📖 **项目全景**：完整架构/模块/数据/部署/优化记录见 **[docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md)**；
> 接手 AI 引导见 **AGENTS.md**。

## 🧠 核心架构（SAIOS）

```
                     ┌──────────────────────────────────────────┐
  目标 + 成长档案 ──▶ │  Mission Orchestrator（任务编排）           │
                     │  perceive → plan → execute → observe     │
                     │            → reflect → learn             │
                     └──────┬──────────┬──────────┬─────────────┘
                            ▼          ▼          ▼
                     ┌──────────┐ ┌──────────┐ ┌──────────────┐
                     │ Agent    │ │Reflection│ │  Evolution   │
                     │ Runtime  │ │  教训库   │ │  成长档案     │
                     │ 实例=身份 │ │ 失败→教训 │ │ 风格/主题/习惯 │
                     │ +目标+记忆│ │ 下次规划  │ │ 注入规划与圆桌 │
                     │ +工具+状态│ │ 注入      │ │              │
                     └──────────┘ └──────────┘ └──────────────┘
```

- **🎯 Mission Orchestrator**：一句话目标出发，AI 拆解计划（带理由）→ 逐步骤执行（真实调用引擎）→ 观察结果 → 失败自动反思 → 教训沉淀
- **🤖 Agent Runtime**：Agent 实例 = 身份 + 目标 + 记忆 + 工具 + 状态；支持多 Agent 编排（导演工作室：主题 → AI 选角 → 一键建组 → 群聊共创）
- **📖 Reflection Engine**：每次失败提炼「教训」入库，下次规划时注入——系统自己会"吃一堑长一智"
- **🌱 Evolution Engine**：成长档案持续聚合你的风格偏好/常用 Agent/步骤习惯，注入规划与创作圆桌
- **⚙️ 12 引擎融合**：music / text / story / image / video / comic / search / asmr / character / memory / agent / code——统一调度、互相供料、结果回填知识库
- **💾 会话持久化**：Mission 历史、Agent 运行记录、成长档案全落库；产物（代码/文档）可打包 zip 下载、可沙箱执行
- **🚪 入口极简**：一个输入框 + 一句话目标，其余全自动——"页面还需要那么多按钮输入框嘛？"（设计信条）

## ✨ 创作能力

- **🎬 创作圆桌**：任何内容领域（音乐/文案/提示词/角色卡/图片/视频/漫画）都能开一场"定制阵容 → 逐轮真讨论（SSE 实时）→ 批评必须带替代方案 → 主编把关定稿"的创作会议；定稿自带结构自检（空洞赞颂词/唱感均衡/押韵偷懒/段落纪律），严重问题自动重写一轮
- **📚 会生长的知识库**：素材入库即由 AI 提炼「精华解读」（核心意象/主题内核/可化用点/化用禁忌）；创作时自动检索注入；**好作品的定稿自动回填知识库**成为后续创作的营养（创作范例）；联网搜索兜底（SearXNG → Wikipedia，先提炼后注入，素材不劫持主题方向）
- **✍️ 人民性创作信条**：写人先立人（开放主题先立具体人物原型）、叙事铁律（一段一景/戏剧时刻）、落地铁律（拒绝抽象空转）——每一场圆桌都执行
- **🎵 音乐创作**：写歌 / 1对1 讨论室 / 多角色圆桌三档；定稿自动打标签（风格/主题/情感）存入作品库，支持搜索、按标签浏览、对比、匿名分享、发布到创作群
- **🤖 角色陪伴记忆**：原创蒸馏 + MemoryCore 多层记忆（L0-L3），对话注入原著档案与回忆
- **💬 创作群聊**：群内 `@AI 写歌`、`@AI 导演` 指令，直接在群内共创
- **🧩 提示词库治理**：content_hash 去重、垃圾清理、主题检索
- **🛡 开源友好**：`.env` 密钥隔离、生产拒绝默认密钥、私有媒体鉴权访问、AgentList 目录可一键产出 Agent 配置

## 快速开始（compose 全栈）

```bash
docker compose up -d --build     # 前端 5000 / API 8002 / MySQL / Redis / worker / MemoryCore :8420
docker compose logs -f api       # 看日志
```

本地开发：

```bash
# 后端（Python ≥3.14，建议 uv）
cd apps/api && uv venv && uv pip install -e .
alembic upgrade head && python -m seed_data
uvicorn app.main:app --port 8002 --reload

# 前端（另开终端）
cd apps/web && pnpm install && pnpm dev
```

## 环境变量

复制 `.env.example` 为 `.env` 后按需修改，关键项：

| 变量 | 说明 |
| --- | --- |
| `APP_ENV` | `development` / `production`。生产环境拒绝默认密钥（`JWT_SECRET_KEY` 等必须配置强随机值） |
| `JWT_SECRET_KEY` / `APP_SECRET_KEY` | JWT 与敏感配置加密密钥，生产必须改 |
| `MYSQL_*` | MySQL 连接（compose 自动注入 `DATABASE_URL`） |
| `STORAGE_PROVIDER` | `local`（默认）/ `r2` |
| `OPENAI_COMPATIBLE_*` | OpenAI 兼容网关（如本地 grok2api），文本/图像/视频真实生成 |
| `SEARXNG_URL` | 本地 SearXNG 聚合搜索（可选，缺省自动降级 Wikipedia） |
| `TDAI_MEMORY_*` | 角色陪伴 MemoryCore 记忆网关（compose 已含服务） |
| `RATE_LIMIT_PER_MINUTE` | 全局限流（0=关闭）；部署在受信代理后置 `TRUST_PROXY=true` |

## 常用命令

```bash
cd apps/api && uv run pytest      # 后端测试
cd apps/web && npx tsc --noEmit   # 前端类型检查
cd apps/web && npx playwright test --project=chromium-desktop --grep-invert @heavy --workers=1  # GUI 测试
```

## 部署

- **compose 全栈**：`docker compose up -d`（前端 + API + MySQL + Redis + worker + MemoryCore）
- **systemd 混合**（服务器）：`bash deploy/scripts/deploy_remote.sh`，详见 `docs/` 规划
- **备份**：`deploy/scripts/backup.sh`（每日 02:00 自动备份到 `backups/`）

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
