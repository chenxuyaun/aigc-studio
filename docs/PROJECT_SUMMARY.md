# AIGC Studio 项目全景总结

> 生成时间：2026-08-07 ｜ 用途：项目交接 / 供外部 AI 或工具接手优化
> 状态：本地生产运行中（Docker Compose），全部功能可用

---

## 1. 项目定位

**AIGC Studio** —— 一站式 AI 创作工作台：

- 文本 / 图片 / 视频 / 语音生成（多模型 Provider）
- 提示词库（14,000+ 条，可搜索/分类/收藏/共享）
- ASMR 资源库（62,000+ 条：作品、封面大图代理、网盘条目）
- AI 角色扮演（角色卡 + 多层记忆 + 原著蒸馏）
- AI 故事创作（项目/章节/版本管理）
- Agent 智能体、技能（Skills）、工作流画布（Workflow Canvas）、写真摄影、素材管理

## 2. 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 19 + Vite + **Module Federation** + PWA（Workbox）+ Tailwind + shadcn 风格组件 |
| 后端 | Python 3.14 + FastAPI + SQLAlchemy async + pydantic v2 |
| 任务队列 | Celery + Redis（beat 定时 + 多队列：text/image/video/audio/import/maintenance） |
| 数据库 | MySQL 8.4（生产）/ SQLite（开发），Alembic 迁移 |
| 记忆 | Tencent MemoryCore（standalone，端口 8420，L0-L3 管道） |
| LLM 网关 | grok2api（本地，OpenAI 兼容 :8000/v1），模型 grok-chat-fast / grok-4.5 / grok-imagine-image-lite |
| 角色聊天 | SillyTavern（本地 :8001） |
| 注册机 | grok-register-agent + turnstile-solver + flaresolverr（**仅本地**，不上云） |
| 构建 | pnpm workspace monorepo；Docker Compose 编排 |

## 3. 仓库结构（monorepo）

```
aigc-studio/
├── apps/
│   ├── web/                  # React 前端（src/pages/ 34 个页面）
│   └── api/                  # FastAPI 后端
│       └── app/
│           ├── api/v1/       # 30 个路由模块（见 §5）
│           ├── core/         # 配置/缓存/安全（redis_lock、限流、CSP）
│           ├── models/       # 44 个 SQLAlchemy 模型
│           ├── services/     # 业务服务（memory_client、character_distill 等）
│           ├── tasks/        # Celery 任务（asmr/agentlist/backup/story/register_batch 等）
│           ├── providers/    # 生成 Provider 抽象（文本/图像/视频/音频）
│           ├── mcp/          # MCP 集成
│           └── storage/      # 文件存储（本地卷 / R2）
├── packages/
│   ├── shared-types/         # 前后端共享 TS 类型
│   ├── eslint-config/        # lint 配置
│   └── tsconfig/
├── deploy/
│   ├── nginx/nginx.conf      # 前端容器 nginx（/api 反代 + CSP）
│   ├── tdai-gateway.yaml     # MemoryCore 配置
│   ├── tdai-prompts/         # L1 抽取 prompt 覆盖（中文强制）
│   ├── cloud/                # 云部署 compose（已退云，保留备用）
│   └── sillytavern/          # 角色聊天配置
├── alembic/versions/         # 数据库迁移
├── scripts/                  # 剧本生成器（替身-30场）等工具脚本
├── docs/                     # 文档
├── tests/                    # 217+ 单元测试
├── backups/                  # 每日自动备份（凌晨 2 点）
├── compose.yaml              # 生产编排（本地主环境）
└── .env                      # 密钥/配置（gitignored，勿提交）
```

## 4. 运行环境（本地主环境，Docker Compose）

**11 个容器**（`docker ps` 全部 healthy/Up）：

| 容器 | 端口 | 作用 |
|---|---|---|
| aigc-studio-frontend-1 | 5000 | 前端（nginx 内含 /api 反代 → api:8000） |
| aigc-studio-api-1 | 8002 | FastAPI（**宿主映射 8002**，8000 被 grok2api 占用） |
| aigc-studio-worker-1 | - | Celery worker + beat |
| aigc-studio-memory-core-1 | 8420 | 记忆网关 |
| aigc-studio-mysql-1 | 3306(内) | MySQL 8.4 |
| aigc-studio-redis-1 | 6379(内) | Redis（requirepass） |
| aigc-studio-sillytavern-1 | 8001 | SillyTavern 角色聊天 |
| grok2api | 8000 | LLM OpenAI 兼容网关 |
| grok-register-agent / grok-turnstile-solver / grok-flaresolverr | - | 账号注册机（本地） |

**数据卷**：mysql_data(1.1G) / storage_data(44M) / tdai_data(记忆 9.6M) / sillytavern_data / redis_data

**开发模式**：前端 `pnpm dev`(:5180) + 后端 uvicorn(:8001 SQLite) 可脱离 Docker。

## 5. 功能模块（页面 ↔ API）

| 前端页面 | API 路由 | 说明 |
|---|---|---|
| PromptsPage / PromptGeneratorPage / PromptOptimizerPage | `/prompts` | 提示词 CRUD、分类、标签、收藏、共享、AI 生成/优化 |
| AsmrPage | `/asmr/works`、`/asmr/…` | 作品/网盘条目、封面大图代理、收藏 |
| RoleplayPage | `/roleplay`、`/memory` | 角色卡、多轮聊天、记忆注入、原著蒸馏 |
| StoryProjectPage / StoryStudioPage | `/story` | 故事项目/章节/版本、AI 续写 |
| AgentsPage / AgentChatPage | `/agents`、`/agentlist` | 智能体目录、对话 |
| SkillsPage / SkillChatPage | `/skills` | 技能库、技能对话 |
| WorkflowsPage / WorkflowCanvasEditor | `/workflows` | 工作流画布（节点编排） |
| ImageGenPage / VideoGenPage / AudioGenPage / TextGenPage / ComicGenPage | `/generations`、`/providers` | 多模态生成任务 |
| PhotographyPage | `/photography` | 写真摄影 |
| KnowledgePage | `/knowledge` | 知识库文档（蒸馏素材源） |
| DashboardPage / LogsPage / TasksPage / UsersPage / ProvidersPage / UpstreamPage | `/dashboard` `/logs` `/tasks` `/users` `/providers` `/upstream` | 管理/监控/注册机状态 |
| SearchPage | `/search` | 全局搜索（覆盖 prompt/story/agent 等 scope） |

## 6. 核心数据模型（MySQL，44 表）

- **用户/权限**：user、refresh_token（JWT 双 token，role: admin/user）
- **内容库**：prompt(+category/tag/source/favorite)、asmr_work(+netdisk_item/favorite)、agentlist_project、skill、workflow(+category)
- **创作**：story_project / story_chapter / story_chapter_version / story_character、generation_task、asset
- **角色陪伴**：roleplay_character / roleplay_chat / roleplay_lore / roleplay_persona、**character_profile**（原著蒸馏档案，含 book_chunks JSON）
- **系统**：provider_config、ai_call_log、inspection_report（每日巡检）、serial_schedule、quick_reply、regex_script、photo(+album)、text_document

**数据规模**（2026-08-07）：asmr_works 62,424 / prompts 14,014 / asmr_netdisk_items ~2,600 / agentlist_projects ~1,400 / story_chapters ~150 / assets ~110 / agents ~90 / skills ~55。

## 7. AI 能力层

- **网关**：grok2api（本地 :8000/v1 OpenAI 兼容），`.env` 的 `OPENAI_COMPATIBLE_*` 配置；model `grok-chat-fast`（默认 `DEFAULT_MODEL`，前端常量 `apps/web/src/lib/constants.ts`）
- **Provider 抽象**：`app/providers/` 支持文本/图像/视频/音频，可切换多个供应商（含 HuggingFace）
- **任务链路**：前端提交 → generation_tasks → Celery（按类型分队列）→ Provider → 结果回存 + SSE 进度（轮询 3s）
- **本地 embedding**：`/v1/embeddings` 端点，n-gram 哈希向量（512 维，中文 1/2-gram，匿名无外部依赖），供记忆检索 hybrid 用
- **注册机**：`/upstream/register`（本地 grok2api 账号自动注册，Redis 锁 4h 互斥）

## 8. 角色陪伴多层记忆系统（核心特色）

**架构**：MemoryCore gateway（agentmemory/memory-core:latest，standalone，:8420）

```
平台 _build_prompt 注入 ←── memory_client（LRU 缓存、5s 超时、静默降级）
         │
         ├─ L0 原始对话（SQLite + JSONL）
         ├─ L1 原子事实（FTS5 + BM25，jieba 中文分词）
         ├─ L2 场景（MD 文件，≤15，heat 管理）
         └─ L3 画像（persona.md ≤2000 字）
```

- **记忆隔离键**：`agent_id=角色卡 asset_id`、`user_id=平台用户`、`session_id=chat_id`
- **LLM 管道**：L1 抽取用 grok2api（`TDAI_LLM_*` env）；`deploy/tdai-prompts/l1-extraction.ts` 挂载覆盖——中文对话强制中文输出 + 角色扮演视角规则
- **embedding**：本地 n-gram 向量（512 维），FTS 词典外词（如"橘猫"）也能命中；fallback query_atomic recent
- **原著蒸馏**（自研）：选知识库文档 → `distill_character_task`（Celery）→ LLM 分步生成档案（身份/性格/说话风格/知识边界/关系网/核心事件 ≤2000 字）→ 存 `character_profiles.book_chunks` → 对话时注入
- **注入预算**：system prompt（档案 ≤800 + 画像 ≤2000 + 场景 top5）+ user prompt（L1 原子 top5 + 原著命中 top3），总注入 ≤2500 字符
- **降级策略**：gateway 不可用全部静默降级，对话不受影响

## 9. 已完成的优化工作（三轮批次 + 专项）

### A. 任务健壮性
- Celery 任务统一 `max_retries=2, autoretry_for=(OperationalError, TimeoutError)`
- Redis 锁（SETNX+TTL）：媒体任务 900s、注册批 4h，跨进程互斥防重复执行
- SSE 轮询 1s→3s；备份任务 `fetchmany(5000)` 分批
- `memory_client` OrderedDict LRU（≤100 客户端）

### B. 安全
- 修复注册机越权（`/upstream/register` 仅 admin）、limit 参数漏洞（分页上限）
- 错误响应统一（`{"success":false,"data":null,"error":{...}}` 结构）
- nginx CSP 双位置注入（server + index.html，location 级 add_header 覆盖问题）
- dashboard 巡检接口仅 admin

### C. 体验质量
- 聊天持久化 MAX_MESSAGES=200 截断
- 模型名常量收敛（DEFAULT_MODEL / FALLBACK_MODELS），消除 5 处硬编码
- logo.png 全站应用（登录页 + 侧边栏 + PWA 预缓存；`.dockerignore` 显式放回）

### 专项：ASMR 搜索性能
- 大图封面 `main_cover_url` 列 + 图片代理（62k 行回填）
- Redis 缓存 + 预过滤（日文标签/标题），搜索延迟显著下降

### 专项：剧本《替身》
- scripts/generate_script.cjs 生成完整 30 场 1 小时悬疑电影剧本 → docx（已交付导演）

### D. 交接后第一轮（2026-08-07）
- `git init` + 基线提交；.gitignore 排除第三方克隆（SillyTavern/、TencentDB-Agent-Memory/）、.cpolar-data/ 等
- worker `DB_POOL_CLASS=null`（NullPool）：消除 asyncio.run 跨 loop 复用连接导致的 `Event loop is closed` 噪音
- 新增 `DB_ECHO` 独立开关（默认关）：SQL 语句不再刷日志；与 APP_DEBUG 解耦，/docs 保持可用
- 根目录 27 个 GUI 测试产物移出版本控制（保留于 .cowork-temp/test-artifacts/）
- 演示账号 brother1-3 密码轮换为随机值并逐个验证登录
- 控制台错误清零（CSP/媒体/接口对齐）：`img-src/media-src` 加 `blob:`（本地媒体预览）；`font-src` 白名单 at.alicdn.com、cdn.yiban.io（AI 内容第三方字体）；`/asmr/favorites` 上限 100→200 对齐前端；MarkdownContent 新增 SmartImg（`/api/` 私有图带鉴权取 blob 渲染，不再 401 破图）；Dashboard 巡检查询仅 admin 发起（普通用户不再 403）

## 10. 部署经验与教训

### 本地（当前主环境）
- `docker compose up -d --build` 一条命令全栈；本地 API 端口 8002（避免与 grok2api 的 8000 冲突）
- 每日 2:00 自动备份 MySQL 到 `backups/`（保留多日，带压缩）

### 云端（已退租，配置保留 deploy/cloud/）
- 曾部署 81.71.32.144：6 核心服务 + grok2api + caddy
- **教训**：
  - 2G 内存 OOM（memory-core exit 137）→ 加 3G swap
  - 国内云无法直连 grok.com（需要代理，且跑 grok2api 有封号风险）→ **决策：grok2api/注册机只本地跑**
  - registry mirror（docker.1panel.live 等）解决 Docker Hub 超时；sillytavern 官方镜像拉不动 → 本地镜像 `docker save/load` 搬运
  - 全新 DB 上 Alembic 迁移 1061 duplicate index（从迁移中移除重复 create_index）
  - MySQL TEXT 列不能有 DEFAULT（1101）→ 迁移移除 server_default
  - pscp 上传只取文件名不保留相对路径 → 上传多文件时必须逐个指定目标路径
  - grok2api 迁移：SQLite WAL 必须停容器 checkpoint 后才可快照；数据卷 owner 要与容器 uid 一致（chown）

### 内网穿透（当前演示方式）
- cpolar 3.3.12（Docker 容器跑 Linux 版，`aigc-cpolar` 镜像 + `--network host`）
- 隧道：`cpolar http 5000`，公网 https://111456a.r21.cpolar.top（免费版随机域名/1Mbps）
- 配置存 `.cpolar-data/`（**勿进 git**）；`docker logs` 无输出，用 `:4040` inspect 面板查隧道 URL

## 11. 当前状态

- ✅ 本地 11 容器全绿，AI 对话/生成/记忆/蒸馏全链路可用
- ✅ 数据完整（62k ASMR / 14k prompt），每日自动备份
- ✅ 217+ 测试通过，ruff/mypy/tsc 全绿
- ✅ 已有 git 版本控制（2026-08-07 `git init` + 首次提交，main 分支）
- 🔶 C 盘清理后需持续关注磁盘

## 12. 已知问题 / 优化候选（供接手者）

1. ~~**无版本控制**~~（已解决 2026-08-07）：git init + 首次提交完成；SillyTavern/、TencentDB-Agent-Memory/（第三方克隆）、.cpolar-data/ 已入 .gitignore
2. ~~**api/worker 日志噪音**~~（已解决 2026-08-07）：worker 服务设 `DB_POOL_CLASS=null`（compose.yaml），database.py 按环境变量切 NullPool——asyncio.run 每任务新 loop，现连现关，不再跨 loop 复用连接；API 进程保持 QueuePool 不变
3. **cpolar 免费隧道**：域名重启后变化、限速 1Mbps；长期分享需付费版或自建 frp
4. **本地 API 端口 8002** 与 grok2api 8000 并存，文档/脚本中需区分；建议统一通过 nginx 反代访问
5. **云端数据无增量同步**（当前为一次性快照；云端已退，本地为唯一源）
6. **内存敏感**：本地 2G 级内存跑 11 容器，任务并发高时注意 OOM；swap 已兜底
7. **SillyTavern 公网暴露风险**（演示隧道只穿 5000，无此问题；但 8001 若开公网需改默认密码）
8. **Caddy HTTPS**：deploy/cloud/ 配置保留，等真实域名后启用
9. **注册机本地化**：groksapi 账号续期/健康监测由本地注册机承担，云上无冗余

## 13. 常用命令速查

```bash
# 全栈
docker compose up -d --build          # 构建并启动
docker compose logs -f api worker     # 看日志
docker compose restart frontend       # 前端重启（nginx 缓存问题首选）

# 备份（自动 2:00，也可手动）
docker exec aigc-studio-mysql-1 sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" aigc_studio' | gzip > backups/manual-$(date +%s).sql.gz

# 记忆
curl http://127.0.0.1:8420/health     # MemoryCore 健康
docker exec aigc-studio-memory-core-1 ls /data/tdai-memory   # L0-L3 数据

# 穿透
docker start cpolar-tunnel            # 开隧道
docker exec cpolar-tunnel wget -qO- http://127.0.0.1:4040/ | grep -oE "[a-z0-9]+\.r[0-9]+\.cpolar\.top" | head -1   # 查当前公网域名
docker stop cpolar-tunnel             # 关隧道

# 测试
cd apps/api && uv run pytest          # 后端测试
cd apps/web && npx tsc --noEmit       # 前端类型检查
```

## 14. 安全边界（红线）

- `.env` 含全部密钥（JWT/DB/Redis/LLM/管理账号）——**绝不提交、绝不打印**
- grok2api 管理凭据仅用于 API 调用，不落文件
- 平台不开放匿名注册（用户由 admin 创建）
- 公网只暴露前端 5000（nginx 反代），API/DB/Redis 均不暴露
- 演示账号：brother1-3（密码已于 2026-08-07 轮换为随机值，由用户本地保管；如需重建：admin 调 `POST /api/v1/users/`）
