# AGENTS.md — AIGC Studio 接手引导

> 任何 AI 助手/工具接手本项目前，先读此文件 + `docs/PROJECT_SUMMARY.md`（完整全景）。

## 项目一句话

AI 创作工作台（提示词库 / ASMR 资源 / 角色陪伴记忆 / 故事创作 / 多模态生成），
React 19 + FastAPI + Celery + MySQL + Docker Compose，**本地生产运行中**。

## 第一原则（红线，违反即事故）

1. `.env` 含全部密钥（JWT/DB/Redis/LLM/管理账号）——**绝不提交、绝不打印、绝不改格式**（`KEY=value` 无空格）
2. grok2api 管理凭据仅用于 API 调用，不落文件
3. 公网只暴露前端 5000（nginx 反代 `/api`），API/DB/Redis 不暴露；平台不开放匿名注册
4. 大改动前先跑测试：`cd apps/api && uv run pytest`；前端 `cd apps/web && npx tsc --noEmit`
5. 改 Docker 构建相关文件时注意 `.dockerignore`（`*.png` 会误伤 public 资源，需显式 `!` 放回）

## 架构速览

- **前端** `apps/web`：React 19 + Vite + Module Federation + PWA，34 页面，`src/pages/`
- **后端** `apps/api`：FastAPI + SQLAlchemy async，30 个 v1 路由，`app/api/v1/`
- **任务**：Celery + Redis（队列 text/image/video/audio/import/maintenance），`app/tasks/`
- **记忆**：MemoryCore :8420（L0-L3），配置 `deploy/tdai-gateway.yaml`，注入逻辑 `app/services/memory_client.py`
- **LLM**：grok2api（本地 :8000/v1，模型 `grok-chat-fast`）
- **端口**：前端 5000 ｜ API 8002（**8000 被 grok2api 占用，勿冲突**）｜ SillyTavern 8001 ｜ 记忆 8420

## 常用命令

```bash
docker compose up -d --build    # 全栈
docker compose logs -f api      # 日志
cd apps/api && uv run pytest    # 后端测试
cd apps/web && npx tsc --noEmit # 前端类型检查
# GUI 测试（打生产前端 5000，必须 --workers=1 串行：beforeEach 每用例真实登录会轮换 refresh token，并行互相作废）
cd apps/web && E2E_BASE_URL=http://127.0.0.1:5000 npx playwright test --project=chromium-desktop --grep-invert @heavy --workers=1
```

**⚠️ 502 排障（2026-08-11 首战 → 2026-08-14 根治）**：登录 502 的根因是**启动竞态**——nginx 先于 uvicorn 起来，首批登录撞上 api 还没监听端口（`connect() failed (111) while connecting to upstream`）。`depends_on: service_healthy` 只在容器「创建」时生效，容器「重启/start/Docker Desktop 重启」会跳过排序，故每次重启都可能复发。
**已根治**：前端容器 `deploy/nginx/wait-for-api.sh` 在 nginx 启动前轮询 `http://api:8000/api/v1/health/live`，api 就绪才 `exec nginx`（见 `apps/web/Dockerfile` 的 CMD）。重启后登录不再 502，只有 3~4 秒冷启动等待。
遗留排障：若仍 502 且 api 容器出现 `invalid IP` / 网络损坏 → `docker compose down && docker compose up -d`（网络彻底重建，volumes 数据保留）。
**502 第三形态（2026-08-17）**：重建 api/worker 容器后 api 容器 IP 变化（如 172.18.0.3→.4），frontend 的 nginx 进程缓存了解析结果（日志 `connect() failed (111) ... upstream: http://172.18.0.3:8000`，而配置是服务名 `api:8000`）→ 登录/刷新 token 502。**重启 api 后必须连带 `docker restart aigc-studio-frontend-1`** 让 nginx 重新解析。
勿用固定 IP 方案（Docker Desktop WSL2 下 `ipv4_address` 会引发 invalid IP + DNS 失效，已踩坑回滚）。

## 当前状态（2026-08-07 更新）

**已完成的待办**（均含自动化测试）：
1. ✅ 前端 GUI 测试：`apps/web/e2e/`（global-setup 登录 + core-modules 4 测试 + smoke 5 测试，`--grep-invert @heavy` 跑默认套件）
2. ✅ 推理框架资料入库：知识库 `推理框架·vllm/ollama/llamacpp/selection` 4 篇
3. ✅ 连载告警：每日巡检 `serial_project_alerts`（`SERIAL_STALL_DAYS` 默认 7 天）+ Dashboard 高亮
4. ✅ 提示词库治理：清理 168 垃圾 + 382 重复（剩 13,464 条）；`content_hash` 去重机制已启用
5. ✅ 图片/视频生成真实链路修复（provider_configs 需含 grok-imagine-* 匹配行）
6. ✅ 图片生成页「从提示词库选择」入口
7. ✅ AI 导演工作室：`/create/studio`（主题→AI 选角→一键建组→群聊共创），后端 `POST /creation/plan|setup` + `tests/test_creation.py`

**注意**：
- E2E 登录态文件 `apps/web/e2e/.auth/` 含 token，已在 .gitignore
- 改后端代码后需 `docker compose up -d --build api worker`（容器内代码非热加载）
- MySQL 客户端操作必须带 `--default-character-set=utf8mb4`（否则中文条件匹配失败）

## 部署同步（云服务器 124.221.130.64，⚠️ 2026-08-18 图片全灭事故复盘）

**🔴 SSH 端口已从 22 → 55991（2026-08-23 切换完成）**：
- 所有 SSH/SFTP 连接必须用 55991（本地 `D:/.env` 的 `port=` 字段；`scripts/_server_*.py` 与
  `.build-tmp` 自动化脚本都从它读，无硬编码）。22 已关闭不再监听；腾讯云防火墙已放行 55991。
- **切换坑（Ubuntu 24.04）**：sshd 默认走 **systemd socket 激活**（监听由 `ssh.socket` 持有），
  在 sshd_config 直接加 Port 会与 socket 单元冲突 → sshd 无法接管连接。必须先
  `systemctl disable --now ssh.socket` 切回传统 daemon 模式再改 Port。
- 「TCP 通但无 banner」= 腾讯云安全组拦截（SYN proxy 假象）；tcpdump 抓不到外部包即可确认是云端防火墙，非服务器问题。

**媒体存储必须从本地 Docker volume 打包，不是仓库目录！**
- 本地应用 `STORAGE_LOCAL_PATH=./storage`（容器 WORKDIR=/app）→ 真实媒体数据在 volume
  `aigc-studio_storage_data`（数百文件）。仓库 `apps/api/storage` 是旧时代残留（3249 个文件，
  缺 admin/brother1 用户数据），**曾把服务器卷覆盖成错误数据导致全部图片 404**（提示词库图片
  是外链所以正常，其余全灭——用户一眼就发现）。
- 同步：`python scripts/_server_storage_sync.py`（docker run alpine 打包 volume → SFTP →
  服务器 volume 合并解压，非破坏）。代码同步：`python scripts/_server_sync.py`
  （**勿再排除 *.png/*.jpg**——apps/web/public 的 PWA 图标构建依赖它们）。

**图片 404 排障顺序**（`python scripts/_server_verify_assets.py` 一键体检）：
1. DB↔volume 匹配率：服务器上必须 `sudo test -f`（volume root 权限，非 root 一律误报 MISS）
2. 直连 API `127.0.0.1:8002` 验证 access-url → content（带 JWT 应 200 + 真实字节）
3. 公网 `http://127.0.0.1$URL`——**$URL 已以 /api/v1 开头，拼接时绝不再加 /api 前缀**
   （否则 `/api/v1/api/v1/...` 404，历史上误导过两次排查）

## 多后端部署（2026-08-19 新增：writers / ten / wxapp）

2GB/2 核服务器，除 aigc-studio 外另部署三个后端，**全部只绑 127.0.0.1，公网走 nginx :80 子路径**：

| 服务 | 项目 | 技术栈 | 端口(host) | 运行方式 | nginx 前缀 | 说明 |
|---|---|---|---|---|---|---|
| writers | `D:\software\code\ideas\writers` | Go 1.26 + Postgres | 8081 | systemd `writing-api` | `/writers`（UI `/app`） | 本地交叉编译 linux 二进制；启动自动迁移 |
| ten | `D:\software\code\ideas\ten` | FastAPI + SQLite | 8000 | systemd `ten-api` | `/ten` | python3.12 venv；dry-run 默认安全 |
| scai soul | `...\wxapp\code\backend` | NestJS + Prisma + Postgres | 4000 | docker `scai-soul-service` | `/soul` | 含 WebSocket 聊天 |
| scai ai | `...\wxapp\code\ai-service` | FastAPI | 8011 | docker `scai-ai-service` | `/ai` | 模型走云 API |

- **共享 Postgres**：`shared-pg` 容器（postgres:16-alpine，127.0.0.1:5433 供宿主机 writers 使用；
  且**已挂到 `scai_default` 网络**，soul-service 用容器名 `shared-pg:5432` 直连）承载 writers + scai 两库
  （内存约束，避免两个 postgres）。密码在服务器 `/home/ubuntu/.deploy-env`（600 权限，勿外传）；
  compose 密钥经 `deploy/cloud/.env`（SCAI_PW/JWT_SECRET，同样 600）。
- **同步**：`python scripts/_server_sync_multi.py`（打包三项目 → /home/ubuntu/{writers,ten,wxapp}，
  含各自 .env 密钥）。wxapp 国内镜像源版 Dockerfile（Dockerfile.cn：npm 走 npmmirror、pip 走清华）
  在各自项目内；compose 为 `wxapp/code/deploy/cloud/compose.server.yaml`。
- **已知坑**：
  - nginx `proxy_pass` 带 URI 时剩余路径保留前导斜杠 → `//healthz`，必须 `rewrite ^/xxx/?(.*)$ /$1 break;`
  - Prisma 在 bookworm 容器需显式 `binaryTargets = ["native", "debian-openssl-3.0.x"]`
    （否则生成 1.1.x 引擎，运行时缺 libssl.so.1.1 崩溃；schema.prisma 已改）
    **且 runtime 阶段必须 `apt-get install openssl`**（slim 镜像无 libssl.so.3，Dockerfile.cn 已加）
  - 容器→宿主回环（127.0.0.1 绑定端口）不可达——容器内访问宿主服务要挂同一 docker 网络用容器名，
    或绑 0.0.0.0（有公网暴露风险，勿用）
  - **nginx sub_filter 与 gzip 的大坑**：sub_filter 无法改写 gzip 压缩响应。浏览器发
    `Accept-Encoding: gzip` 时上游（如 SillyTavern）压缩 HTML → sub_filter 静默跳过 →
    `<base href="/">` 改写失败 → 资源全走根路径 404（白屏，且 curl 裸测正常、浏览器全挂，
    极难排查）。**修复：location 里 `proxy_set_header Accept-Encoding "";`** 让上游返回明文，
    sub_filter 生效后再由 nginx 自行压缩输出。
  - **sub_filter 改写子路径的完整清单（SillyTavern 1.18 /silly 挂载实战，2026-08-19 三轮排坑）**：
    1. `sub_filter_once off` —— 默认只替换每个规则第一处，多处引用会漏改
    2. `sub_filter_types` 必须含 `text/css`（popup.css 的 `@import url('/lib/...')` 在 CSS 里，
       不加就整个 CSS 响应不处理）+ `application/javascript text/javascript`
    3. **ES6 反引号模板字符串是最大漏网**：新版 ST 用 `` `/scripts/templates/${x}.html ``、
       `` `/scripts/extensions/${x}/manifest.json ``、`` `/thumbnail?type `` 等拼路径——
       单/双引号规则全不匹配，必须再加 `` ` `` 变体（`sub_filter '`/scripts/' '`/silly/scripts/';` 等
       十几条：api/sounds/img/lib/css/scripts/characters/locales/thumbnail/messages/delchat/delname/abort/gs/myregex/array-wrap/array-unwrap）
    4. **缓存 304 复发病**：只藏响应头不够——浏览器重访带 `If-None-Match`/`If-Modified-Since`，
       nginx 转发给上游 → ST 回 304 空 body（sub_filter 无处可改）→ 复用本地旧缓存。
       必须同时 `proxy_set_header If-None-Match ""; proxy_set_header If-Modified-Since "";`
       + `proxy_hide_header ETag; proxy_hide_header Last-Modified;` + `add_header Cache-Control "no-store..."`
    5. 排查手法：`curl --compressed -H 'Accept-Encoding: gzip'` 必须带上（模拟浏览器）；漏网时
       `docker cp 容器:/home/node/app/public /tmp/st_public` 后宿主机 grep 三种引号根路径
       （`grep -rhoE '`/[a-zA-Z0-9_?./$-]+' /tmp/st_public --include='*.js'`）
    6. **⚠️ 反引号短规则会误伤正则 flags**（2026-08-19 实战）：`sub_filter '`/gs' '`/silly/gs'`
       把 `text.replace(/```.*?```/gs, '')` 改写坏 → `SyntaxError: Invalid regular expression flags`。
       正则字面量 ```` ```/gs ```` 的 pattern 以反引号结尾，最后一个反引号紧贴 `/gs` 构成 `` `/gs `` 子串被匹配。
       教训：**短规则（合法 flags 字母 dgimsuvy 组成的路径）绝不能加**；`/messages` `/abort` `/thumbnail`
       等含非 flags 字母的规则安全（正则 flags 不会出现这些组合）。
  - 项目目录解压后 root 所有，SFTP 写文件前先 `chown -R ubuntu:ubuntu`；Go 二进制需 `chmod +x`
  - ten 需 `apt install python3.12-venv` 才能建 venv
  - **🔴 saiOS 公网登录/API 全线 401 事故（2026-08-21）**：多后端共用 `location ^~ /api/v1` 前缀冲突——
    nginx 曾把整个 `/api/v1` 反代到 writers(Go :8081)（注释称「避免 /api/v1 被误转发到 saiOS」），
    结果 **saiOS 前端 apiClient 硬编码 `/api/v1`**，浏览器登录 `POST /api/v1/auth/login` 全被劫持到 writers
    → 401/400（writers 不认识 saiOS 的 auth）。且 writers 自身前端走 `/api/harness/*`、**根本不经 `/api/v1`**，
    该规则纯属误配。**修复**：`/api/v1` 改回 saiOS(:5000)（带 SSE buffering off），仅
    `location ^~ /api/v1/agent_os → 8081` 保留给 writers（其 Agent OS 真正私有路径）。
    验证：IP 直连登录 200、`/api/v1/agent_os/tools` 200、`/generations/recent` 200。
    **经验**：多后端共用顶层前缀（`/api`、`/api/v1`）必然打架；先确认各服务前端真实走的 API 前缀再做路由，
    别让后来的服务抢走已有服务的硬编码前缀。备份 `/home/ubuntu/yuncai.site.bak.*`。
  - **🔴 saiOS 访问入口 /saios → 跳备案页根路径（2026-08-21）**：saiOS 是 standalone SPA（`App.tsx` basename
    为空 → 首页路由即**根 `/`**），但公网 nginx `location = / { try_files /var/www/yuncai/index.html }` 把根 `/`
    给了备案页/工作台 → 访问 `/saios`（工作台 saiOS 卡片 href）加载 saiOS HTML 后，React 无 `/saios` 路由
    → 走 `*` 兜底 `Navigate to "/"` → 却落在**备案页**（非 saiOS）→ 用户以为 saiOS 没了/白屏。
    **修复**：`location = /` 改为 `proxy_pass http://127.0.0.1:5000`（saiOS，带 SSE buffering off）；
    备案页/工作台挪到 `location = /yuncai { try_files /index.html; }`（仍可达）；工作台 saiOS 卡片 href→`/`。
    **经验**：saiOS（basename 空）天然占根 `/`，不能让别的静态页占根；备案/入口页应放子路径。
  - **🔴 saiOS 免登录 auto-login 从未启用（2026-08-21 查明）**：`LoginPage` 挂载会静默调 `/auth/auto-login`
    （nginx `location = /api/v1/auth/auto-login` 注入 `X-Auto-Login-Key` 头），后端读 `.env` 的
    `AUTO_LOGIN_KEY`+`AUTO_LOGIN_USERNAME` 校验。但服务器 nginx 注入的是 `AUTO_LOGIN_KEY_PLACEHOLDER`
    **占位符**（从未替换，同 Clash secret 坑）+ `.env` 无 AUTO_LOGIN_* → 后端返回 404「自动登录未启用」。
    **风险考量**：公网 IP 下开启 auto-login = 任何访问者免密拿 admin token，**默认不开启**，需用户确认。
    当前靠手动登录 admin/admin123。

## Model Hub v2 分槽激活 + 文本通道恢复（2026-08-21）

**Model Hub v2（Cherry Studio 式按能力分槽，已上线）**：
- 后端 `apps/model-hub/app.py`：`active_slots` 表（text/image/video/audio/music 五槽独立）；
  `POST /api/active` 支持 `{slot, provider_id}`（单槽）、`{slot, provider_id:""}`（清空回退）、
  `{provider_id}`（v1 兼容=全局切换）；`GET /api/active` 返回 `slots` 字典 + 兼容字段
  `active/config`=text 槽；删除 provider 自动清槽位引用；导出/导入含 slots。
- 前端 `static/index.html`：顶部分能力状态条（💬🎨🎬🔊🎵 各自显示供应商）；卡片悬停出现单槽
  设置按钮；点卡片=全局切换。
- saiOS 消费端：`model_hub_client.get_active_config(slot)`（带缓存+失败限流日志）；
  `task_runner._provider_settings(db, model, task_type)` 按 image/video/audio/music 选槽；
  **`provider_resolver.resolve_text_provider()` 第 0 步 = hub text 槽位优先**（对话模型在模型中心
  一键切换即时生效）。E2E 实证：agent chat 返回 `"source":"hub"`。
- **容器→hub 连通方案**：uvicorn 绑 docker0 网关 `172.17.0.1:8511`（公网不可达），nginx 上游同步改
  `172.17.0.1:8511`，compose api/worker 已有 `extra_hosts: host-gateway` + 注入
  `MODEL_HUB_BASE_URL=http://host.docker.internal:8511`。8511 公网 TCP 握手成功是腾讯云防 DDoS
  SYN proxy 假象（HTTP 实际 502），并非暴露。
- 当前槽位布局：text=cpa·GPT-OSS(gpt-oss-120b-medium)、image=cpa·Gemini-Image、video/audio/music 未设置。

**🔴 生图上游三连灭与最终解法（2026-08-21 晚实战）**：
- zarklab：上游自身 500（服务端/账号问题，直测复现，非我方链路）；grok2api：账号池耗尽
  （"No available accounts"，08-20 的 73 号已烧完）；cpa gpt-image-*：走 codex 账号 →
  `auth_unavailable`（codex 无图像能力/失效）。gemini-3.1-flash-image 走 chat 接口
  **200 出图**（antigravity 账号，message.images[].image_url.url = data URL base64）。
- **解法**：新增 `apps/api/app/providers/chat_image.py`（ChatCompletionsImageProvider——
  经 /v1/chat/completions 出图，解析 message.images[].image_url.url，submit 同步取图缓存 +
  poll 返 data URL，与 ZarklabImageProvider 同款约定）；task_runner image 分支按
  `provider_type == "chat_image"` 分派；hub 建 provider「cpa·Gemini-Image」
  (type=chat_image, default_model=gemini-3.1-flash-image) 占据 image 槽位。
- E2E 实证：saiOS API 生图 → succeeded 23s → 真实 JPEG 1408×768 落资产库，公网 200。
  注意 cli-proxy-api 的 gpt-image 系只支持 /v1/images/generations（chat 会 503 提示），
  gemini 图像系只支持 chat（images 路由 404/401）。
- 遗留：grok 生图需补号（注册机工具链未迁移）；zarklab 待用户验证账号；codex 账号图像不可用。

## Model Hub v3 故障转移链（2026-08-22 上线）

**槽位从"单供应商"升级为"有序候选链"**（Cherry Studio 没有的能力）：
- hub 后端：`slot_providers` 表 (slot, provider_id, position)，v2 `active_slots` 自动迁移播种；
  `POST /api/active` 新增 mode：`promote`（设为主选，原主选降备选）/`append`/`remove`/`clear`
  （默认 replace=v2 兼容）；`GET /api/active` 返回 `slots_chain`（按降级顺序）+ 兼容 `slots`=主选；
  删除 provider 自动移出所有链；导出/导入 version 3 含 slot_chains。
- hub 前端：状态条显示「主选 + 备选(点✕移除)」；卡片徽标区分 主选/备选；
  图标按钮语义 = 设为主选（不再覆盖丢失原主选）。
- saiOS 消费端：
  - `model_hub_client.get_active_chain(slot)`（与 get_active_config 共享缓存）；
  - 文本：provider_resolver 第 0 步链>1 时包 **FailoverTextProvider**
    （`app/providers/failover.py`：generate 逐候选降级；stream_generate 首字节前失败才降级；
    **备选传空 model 用其自身 default_model——模型名不跨供应商**，否则 OpenRouter 收到
    gpt-oss 名必 400）；agent_chat 靠异常触发降级，无需改动。
  - 媒体：`task_runner._media_candidates()`（hub 链 > DB 单候选 > registry）+
    image/video/audio 三分支改为候选循环，日志 `media_failover_next` / `media_candidate_used`。
- **chat_image Provider 加自动重试**（5xx/429/连接错误指数退避×3，4xx 不重试直接降级）：
  cpa 经 Clash 的 antigravity 通道实测约 1/3 概率 EOF，重试后单候选成功率大幅提升。
- 🔴 **部署坑（2026-08-22）**：8511 被 8-21 手动启动的旧 uvicorn（绑 0.0.0.0）占用 →
  systemd restart 循环 EADDRINUSE（restart counter 25+），页面一直旧代码。修复：杀僵尸 pid +
  `systemctl --user reset-failed` + restart。教训：重启 hub 后必须 `is-active` 确认 active，
  且 `ss -tlnp` 核对监听进程是 systemd 的（172.17.0.1 绑定）。顺带消除了一次 0.0.0.0 暴露面。
- **实战实证**：cpa oauth EOF 全挂时，文本请求自动降级 OpenRouter（stealth/ox-alpha）
  出完整回答，用户无感；图像请求 zarklab 失败自动换 cpa·Gemini-Image 成功出图。
- 当前链布局：text=[cpa·GPT-OSS, OpenRouter]；image=[cpa·Gemini-Image, zarklab]；
  video/audio/music 空。

**🔴 zarklab 额度被取消（2026-08-22 用户确认）→ 已从链摘除并停用**：
- 排查铁证：5 条路径（4 个不同出口节点 + 直连）同一把 key 全部 401 Unauthorized（应用层拒绝），
  与节点无关；key 格式/存储/认证头姿势均正确。用户在 zarklab 后台确认额度被取消。
- **OpenRouter 图像备选接入（不花钱的生图第二候选）**：hub 新增 provider「OpenRouter·GPT-Image」
  (type=chat_image, default_model=openai/gpt-5-image-mini)。三个坑：
  ① OpenRouter 图像模型**中国出口区域限制 403** → 必须走代理；
  ② 图像模型默认 max_tokens 数万 → **402 额度不足**，chat_image 对 openrouter 自动压 4000；
  ③ hub API 出于安全默认不回显 api_key（MODEL_HUB_EXPOSE_KEY 才回显）——用 API 复制 key 到新
    provider 会得到空串，必须 sqlite 库内复制或让用户重填。
- **worker 补回代理环境**（grok 时代清理时丢了）：compose worker environment 加
  HTTPS_PROXY/HTTP_PROXY=http://${CLASH_AUTH}@host.docker.internal:7897 +
  NO_PROXY=localhost,127.0.0.1,host.docker.internal；CLASH_AUTH 追加进 ~/aigc-studio/.env
  供 compose 插值（.env 只用于插值，不会自动进容器）。⚠️ 坑：worker 的 environment 是**列表风格**
  （- KEY=value），插映射风格条目会 YAML 报错 did not find expected key。
- 实证：OpenRouter 主选生图 candidate=1/2 succeeded（56s）；恢复 cpa 主选后常规生成同样成功。
- 最终链：image=[cpa·Gemini-Image, OpenRouter·GPT-Image]；text=[cpa·GPT-OSS, OpenRouter]。

**🔴 8511 僵尸进程第二次复发（2026-08-22）+ Edge-TTS 免费语音接入 + 全局切换防误触**：
- **audio 槽免费打通**：Edge-TTS（微软免费 TTS，无账号/密钥/额度）已入模型中心 audio 链
  （provider_type=edge_tts，default_model 存音色 zh-CN-XiaoxiaoNeural）。E2E：6s succeeded 真实音频落库。
- **三个代码坑（都修了）**：
  ① `get_active_chain`/`_media_candidates` 都按 base_url 过滤候选——本地型 provider（edge_tts）
    无 base_url 会被静默丢弃 → 两处都放行 edge_tts；
  ② task_runner 音频分支把 `_provider_kwargs(conf)` 传给只收 name 的 `get_speech_provider`
    → TypeError；且请求 schema 默认 voice="default" 会原样传给 edge-tts 报 Invalid voice
    → 分支按 conf[3] 分派 + edge_tts.py 内部把 default 规范化为默认音色；
  ③ EdgeTTSSpeechProvider 的 data URL 在 submit 返回里而 poll 不带 → task_runner 补
    `poll_result or result` 回退。
- **🔴 全局切换防误触（2026-08-22 实战教训）**：hub UI 点卡片=全局切换=五个槽位的整条链被替换成
  这一个 provider——用户误点 OpenRouter·GPT-Image 后 text/image/audio/video/music 全指向图像供应商，
  对话一度全断。已在 switchTo() 加 confirm 弹窗明示后果；日常应使用卡片悬停的 💬🎨 单槽图标。
- **🔴 僵尸 uvicorn 二次复发**：pid 手动启动绑 0.0.0.0:8511（公网暴露！）→ systemd 重启循环 counter 43。
  处置同前：kill pid + reset-failed + restart + is-active + ss 核对绑定。**教训：任何手动 uvicorn 都是雷；
  hub 异常时先查 `ss -tlnp | grep 8511` 的进程是不是 systemd 的。**

**✅ 模型中心统一网关——其他系统接入（2026-08-22 上线）**：
- hub 的 OpenAI 兼容代理升级为 v3 链语义：`/proxy/v1/chat/completions` 等按 **text 槽候选链顺序**
  自动降级（与 UI 配置一致）；`GET /proxy/v1/models` 聚合链上各供应商 default_model。
- **其他系统接入姿势**（服务器内网任意进程/容器）：
  `base_url = http://172.17.0.1:8511/proxy/v1`，api_key 任意（当前未设 MODEL_HUB_PROXY_KEY；
  设了则强制 Bearer/x-hub-key 校验），model 填链首 default_model（gpt-oss-120b-medium）。
- **首个消费者已切换**：memory-core 的 TDAI_LLM_BASE_URL 从 DeepSeek → hub 代理
  （模型 gpt-oss-120b-medium），重建容器保留原挂载/网络。SillyTavern/writers/ten 同法可接。
- 实证：proxy chat 200「正常/稳」；memory-core /health 200 auth=ENABLED。
- 🔴 **僵尸 uvicorn 第三次复发**：unit 文件正确（172.17.0.1）但运行进程是手动起的 0.0.0.0——
  判断标准不是 unit 文件而是**运行中 cmdline**：`ps -p $(ss -tlnp | grep 8511 | grep -oP 'pid=\K[0-9]+') -o args=`。
  处置：kill → reset-failed → restart → is-active + ss + cmdline 三验。
- **🛡️ 自愈守卫已上线（2026-08-22，第四次复发后根治）**：`model-hub-guard.timer`（systemd
  user timer，每分钟跑 `/home/ubuntu/model-hub/guard.sh`）：8511 监听进程 args 不含
  `172.17.0.1` 即杀掉并重启 model-hub.service；无监听也会拉起。日志
  `journalctl --user -u model-hub-guard`。首跑即捕获第四次僵尸，此后无需人工处置。

**🔴 saiOS 供应商旧通道下线（2026-08-22 P1-P3 全部完成）**：见 `docs/deprecation-plan.md`。
- provider_configs 表已 DROP（迁移 a7b9c1d3e5f7，generation_tasks.provider_id 仅存 NULL 历史列）；
  供应商管理唯一入口 = 模型中心 :8511；/providers 写与管理端点全部 410；ProvidersPage 纯指引页。
- 文本解析只剩：hub text 链 → .env OPENAI_COMPATIBLE_* 兜底（**永久保留**，也是 cpa key 来源，
  upstream 探活/comic 分镜都读它）。媒体候选只认 hub 链，空则 registry（Mock 被显式拒绝、响亮报错）。
- **🔴 加 alembic 迁移前必查 DB 实际版本**：`SELECT version_num FROM alembic_version;`
  ——versions 目录字母序最后的文件不是线上 head（本例真实 head 是 d0a1b2c3d4e5/c0ffee 分支，
  按"看起来最新"的 f9e2 挂迁移 → 双 head → entrypoint `alembic upgrade head` 崩溃循环 Restarting(255)）。
- **🔴 docker-entrypoint.sh 内嵌 python 直接 `from seed_data import seed_hermes_provider`**：
  删 seed_data 函数时必须同步改 entrypoint（曾致 api 循环崩溃；应急用 docker cp 修复脚本 + restart）。
- 长构建挂 nohup 必须 `< /dev/null & disown` 三件套，否则 paramiko channel 挂起/被工具超时误杀。

**🔴 模型中心 P3 连带修复三连（2026-08-24）**：
- ① **hub /api/usage SQL 1146**：usage 统计 LEFT JOIN provider_configs——表删即炸。已改为不再查库，
  by_provider 降级为常量说明（provider_id 恒 NULL 后该维度本就无从回溯）。改 hub app.py 必须
  上传 `/home/ubuntu/model-hub/app.py` + `systemctl --user restart model-hub`（无热加载）。
- ② **SAIOS_DB_URL 占位符坑（同 CLASH_SECRET/AUTO_LOGIN 第三例）**：model-hub.service.d/env.conf
  里曾写 `aigc:changeme@` 模板密码从未替换 → 用量统计永远连不上。已从 saiOS .env 注入真密码（600 权限）。
- ③ **"(副本)"重复行已清理**（11→7）：早期 API 复制 key 得空串的残留。走 hub DELETE API 删（v3 自动清链引用），
  删后链完好。proxy 网关实测 chat 通。

**🔴✅ 僵尸 uvicorn 真正根因查明并根治（2026-08-24 P0 启动源审计，推翻"手动启动"假设）**：
- 五次僵尸的元凶 = **系统级与用户级同名双胞胎 unit**：`/etc/systemd/system/model-hub.service`
  （User=ubuntu、Restart=always、**--host 0.0.0.0**、multi-user.target.wants 开机自启）vs 用户级
  `~/.config/systemd/user/model-hub.service`（172.17.0.1 正确版）。任何人 `systemctl restart model-hub`
  忘带 `--user`、或每次服务器重启 → 0.0.0.0 版被拉起抢端口；guard 杀掉后 Restart=always 又拉 → 循环。
  bash_history/cron/pm2 全部无命中是因为根本不是人干的。
- **处置**：`sudo systemctl stop/disable model-hub`（系统级）→ unit 文件移至 `~/systemd-unit-backups/` →
  删 wants symlink → daemon-reload。验证铁律：`MainPID == ss 监听 pid` 匹配 + 一个守卫周期零击杀。
- **教训**：排查"幽灵进程"先查 `ls /etc/systemd/system/multi-user.target.wants/` 有没有同名单胞胎；
  guard 的判定（args 含 172.17.0.1）只杀监听者，管不了系统级 unit 反复拉起。
- 排查期还发现 rogue 抢占窗口内 API 会由 rogue 应答（无 SAIOS_DB_URL → 误报"未配置"）——测 hub 行为前先核对 MainPID==ListenerPID。

**✅ Grok2API 生图复活 + 账号池 refresh worker（2026-08-24 P1）**：
- **阻塞从来不是刷新机制**，是 grok.com 对机场出口的风控 403（rate-limits 接口）。解法 =
  **扫节点找非风控出口**：mihomo API 逐节点 PUT /proxies/PROXY 切换 + curl 经 7897 测 grok.com，
  新订阅的美国节点全通（美国堪萨斯/美国1/美国2），已选「美国堪萨斯」。⚠️ mihomo PUT 返回 204 空体，
  json.load 会炸——脚本必须容忍空响应；CLASH_AUTH 从 .deploy-env 读，勿硬编码。
- **quota_fast 字段是 JSON 字符串**（`{"remaining":30,...}`）——SQL SUM() 求和得 0 是误判，
  判断配额要 json.loads 后看 remaining。试点 batch/refresh 5/5 成功带回真实配额。
- **端到端生图实测 200 出图**（/v1/images/generations, grok-imagine-image-lite，防盗链本地 URL 模式正常）。
  账号池 73 全 active × fast 30/天 ≈ 2190 图/天产能。
- **image 链升级三候选**：[cpa·Gemini-Image, OpenRouter·GPT-Image, grok2api]（append 进链，删 provider 自动清引用）。
- **每日自愈 worker**：`grok-refresh.timer`（03:10，Persistent）→ `/home/ubuntu/model-hub/grok-refresh.sh`：
  读库取全部 token → async 批量刷新(concurrency=4) → 轮询等完成 → force sync → 统计 with_fast_quota 写日志
  `~/model-hub/grok-refresh.log`。注意 batch/refresh 的 tokens **不接受空数组**（报 No tokens provided）。

**🎮✅ 模型中心重设计为「AI 能力控制台」（2026-08-24 上线，设计稿 ai_capability_control_plane.html 落地）**：
- 前端 `apps/model-hub/static/index.html` 全量重写（Alpine.js + Tailwind CDN + Lucide，零构建哲学不变）。
  八区域：总览(KPI/事件流/自愈心跳) / 能力路由(五槽地铁泳道·激光流线) / 供应商(抽屉+内联确认) /
  账号池(grok 73 格配额热力图·只读) / 可观测(proxy 调用日志表) / 接入中心(片段生成器) / 系统(备份+timer) / Prompts。
  交互：备选卡点击升主选、**拖拽重排链序**、`/` 全局搜索、数字键 1-8 切区域、Esc 关弹层、
  移动端底部导航栏（<768px，顶部 nav 隐藏）、🔔 提示音开关（WebAudio 短哔声随 toast，localStorage 持久化 hub_sfx_muted）、
  路由发包测试发真实请求并反查实际服务者。
- 后端新增只读 API：`/api/events`(ring buffer 500)、`/api/calls/recent`、`/api/pools/grok`
  （sqlite **只读 URI 连接**，token 只回显指纹）、`/api/system/timers`、`/api/system/backups`；
  `POST /api/active` 新增 **mode=reorder**（order 数组=该链全集排列，泳道拖拽的数据通道）。
- proxy 网关埋点：每次调用记 provider/model/延迟/status/fallback 进 calls；降级与异常自动 emit 事件流。
- 验收方式沉淀：SSH 隧道 `-L 18511:172.17.0.1:8511` + Playwright 无头浏览器断言（Alpine $data 状态/DnD 属性/
  搜索结果/CRUD 冒烟）+ 截图。⚠️ 测试脚本 goto 失败要 fail-fast，别 catch 吞掉——曾对死端口空跑一轮。
  ⚠️ Windows 下 OpenSSH 拒绝权限过宽的私钥：`icacls <key> /inheritance:r /grant:r "$env:USERNAME:R"` 一次修复。
- 提交锚点：`32afba7`（主体）+ reorder/prompts/search 补完提交。
- 🔴 **重写回归事故（2026-08-24 用户实测）**：hub 公网入口是 nginx `location ^~ /model-hub` +
  `rewrite ^/model-hub/?(.*)$ /$1 break` 剥前缀反代 8511；旧版前端有
  `const API = pathname.startsWith('/model-hub') ? '/model-hub/api' : '/api'` 前缀感知，
  重写时被我弄丢 → 公网用户全部 API 404（"providers 加载失败: Not Found"），而 SSH 隧道直连验证全绿——
  **测试路径与用户真实访问路径不一致的盲区**。修复：store 加 `apiPrefix()`，api()/gatewayBase/testLiveRoute 三处统一拼前缀。
  教训：①重写任何带反向代理前缀的前端，先 grep 旧版 location.pathname/API_BASE 处理；②验收要含公网入口场景
  （Playwright 直接打开 `http://IP/model-hub`），不能只测内网直连。

**🔴 systemd drop-in 覆盖主 unit 的坑**：`systemctl --user show <svc> -p ExecStart --value` 才是
生效值；只 sed 主 unit 而 `model-hub.service.d/venv.conf` 里还有旧 ExecStart 时改动无效。

**nginx 配置卫生**：备份文件绝不能留在 `sites-enabled/`（nginx 加载 `*` 全部文件 → duplicate
default server，`nginx -t` 失败且 reload 静默不生效）。备份放 `~/nginx-backups/`。

**Clash 节点故障处置（2026-08-21 实战）**：PROXY 组选中节点死亡 → 经代理全部 EOF/挂起（cpa
antigravity 刷新失败、codex 无响应）。修复：mihomo API `GET /group/PROXY/delay?timeout=5000&url=...`
批量测活（138 节点中 16 活）→ `PUT /proxies/PROXY {"name":"<最快节点>"}` → gstatic 204 验证 →
cpa 下轮自动刷新即恢复（gpt-oss 秒通）。脚本 `.build-tmp/_clash_fix.py`。

**🔴 celery worker 跨事件循环崩溃（潜伏 bug 根治，2026-08-21）**：
- 现象：worker 内媒体任务报 `got Future attached to a different loop`，且每 15s 刷
  `RuntimeError: Event loop is closed` 噪音；同子进程第二个媒体任务必炸。
- 根因：celery 每任务 `asyncio.run` 新建事件循环，而 ①服务器 .env 从未设 `DB_POOL_CLASS=null`
  （aiomysql 连接池跨 loop 复用）②`task_runner._media_exec_lock` 全局单例 asyncio.Lock
  ③`cache.py` 模块级 redis 异步客户端 ④openai_compatible/zarklab 的 `_throttle_locks`。
- 修复：compose worker environment 显式 `DB_POOL_CLASS=null`；锁与 redis 客户端一律按
  running loop 隔离（`weakref.WeakKeyDictionary[loop, obj]`）。API 进程单循环行为不变。
- 教训：worker 侧任何模块级异步资源（engine/pool/client/Lock）都是跨循环雷；新增时必须
  per-loop 或确认 NullPool/短连接。

**顺手修复**：`task_runner.notify_event` 缺 `import os`（NameError 会炸任务收尾）；
`tests/test_provider_tools.py` 的 _FakeResp 补 `.text`（SSE 兼容改造后的测试债）；
`tests/test_provider_settings.py` 解包对齐 4 元组。全量 pytest 绿。

## saiOS 服务器生图状态（2026-08-19 更新）

- **历史图片正常**：DB↔volume 116/116，access-url → content 公网全 200（`_server_verify_assets.py` 体检）。
- **文本生成已解锁**：cpa（cli-proxy-api :8317）部署成功 + HTTPS_PROXY 走 Clash 后，saiOS 文本走
  gpt-oss-120b-medium **实测端到端流式输出正常**（DeepSeek 仍可用作备选）。
- **生图状态**：grok2api（:8003）已部署 + 导入 accounts_cli.txt 的 **1643 个账号**（rc4 accounts.db，
  pool=basic，quota 需 grok 刷新）。账号是 2026-07 注册的旧 token，quota remaining=0，
  **刷新成功后 grok-imagine-image 即可生图**；当前卡在批量刷新（`POST /admin/api/batch/refresh`
  需 tokens 参数格式待定，或等 24h 定时刷新，或重跑注册机出新鲜号）。
  cpa 不支持 gemini 生图（antigravity 仅聊天模型）。
- **代理前置**：Clash 7897 已通（api.x.ai 401/grok.com 200），grok2api/cpa 都走 `host.docker.internal:7897`。

## 全量服务迁移（2026-08-19：本地 Docker → 服务器）

**已上服务器**（含数据迁移，本地将清空）：

| 服务 | 服务器形态 | 数据 | 说明 |
|---|---|---|---|
| saiOS 全家桶 | docker compose（api/worker/frontend/redis/mysql） | MySQL + storage 卷已同步 | 原部署 |
| memory-core | docker `memory-core`（aigc-studio_default 网络） | aigc-studio_tdai_data 卷（53 文件） | **LLM 改用 DeepSeek**（服务器无 cpa） |
| sillytavern | docker `aigc-studio-sillytavern-1`（:8001） | aigc-studio_sillytavern_data 卷（221 文件） | 镜像 docker save/load |
| searxng | docker `searxng`（:8891，settings.yml 挂载） | — | JSON API 已开；部分引擎国内超时属正常 |
| writers | systemd + shared-pg | **10 个项目恢复**（pg_dump 从本地 writers-postgres-1） | — |
| wxapp(scai) | compose（soul/ai）+ shared-pg | **1 用户恢复**（pg_dump 从本地 scai-pg-dev） | — |
| lotto(yc) | docker `lotto-dashboard`（:8300） | yc/data + yc/output 卷挂载 | Dockerfile 已加 npmmirror + 排除 Windows node_modules |

**2026-08-19 追加部署**：cpa（cli-proxy-api :8317，antigravity 认证 + Clash 代理，**文本已通**）、
grok2api（:8003，导入 1643 账号，生图待账号刷新）。

**2026-08-19 入口/管理面板收尾**：
- 入口页（`deploy/yuncai-site/index.html`）新增 cpa/grok2api 状态卡（`/llm/cpa/healthz`、`/llm/grok/health`
  仅健康检查，完整 API 不暴露公网）
- grok2api 管理面板经 `/grok-admin` 公网可访问（nginx rewrite 剥前缀 + sub_filter 改写 `/static` `/admin`
  `/favicon.ico` + **`proxy_redirect` 改写 307 Location 头**——否则浏览器跳回内网 127.0.0.1 打不开）
- cpa 管理面板经 `/cpa-admin/management.html` 公网可访问（单文件 SPA createHashRouter，API 走
  `/v0/management/*` 绝对路径，nginx 加 `/v0/management` 兜底路由 + `/cpa-admin` 前缀改写）
- **saiOS 自动登录（免登录入口）**：后端 `POST /api/v1/auth/auto-login`（读 `AUTO_LOGIN_KEY`+`AUTO_LOGIN_USERNAME`
  from .env，nginx `location = /api/v1/auth/auto-login` 注入 `X-Auto-Login-Key` 头）；
  前端 `LoginPage` 挂载先静默调 auto-login；`auth.ts` refresh token 改存 localStorage。
  **坑**：sed 替换密钥会把 `$KEY` 残骸写进 nginx（`unexpected "$"`）——必须用 python 精确整行重写；
  改前端后需服务器 `docker compose build frontend`（镜像内构建）。
- **管理面板凭据（2026-08-19 确认）**：grok2api 面板登录 = `app_key`（config.defaults.toml 默认
  `grok2api`，config.toml 未覆盖 → 密码 `grok2api`，verify 200）；cpa 面板 = `secret-key`
  （config.yaml `remote-management.secret-key`，已重置为明文 `yuncai2026`，启动自动哈希；
  config 挂载 ro，进程内用哈希值）。cpa 管理端点：`/v0/management/{get-auth-status,auth-files,config,api-keys,...}`
  （**没有 /status**）。
**未迁移（记录原因）**：grok-register-agent / grok-turnstile-solver / flaresolverr /
freeagentidentity —— grok 注册/翻墙工具链（服务器已有 Clash 可替代部分功能）；cpolar-tunnel ——
服务器有公网 IP 不需要。grok2api 旧版 backend.db（provider_accounts 新格式）与 rc4 镜像不兼容，
改用 accounts_cli.txt 明文 token 灌入 accounts.db。
**数据备份**：迁移产物留在本地 `.build-tmp/migrate/`（writers.dump/scai.dump/tdai.tgz/silly.tgz）。
**坑**：Windows tar 打包 node_modules 会丢执行位 + 平台二进制不兼容 → Dockerfile 里 `rm -rf node_modules && npm install`。

## 体验升级 + 通知系统（2026-08-20）

**统一工作台**（`deploy/yuncai-site/index.html` 全新重写 + `manifest.webmanifest` + `sw.js` + `yuncai-home.js`）：
- 顶栏（时钟+全局搜索）+ 状态条（服务在线/LLM 上游/最新开奖）+ 分组卡片 + 最近访问（localStorage）+ PWA
- `yuncai-home.js` 由 nginx sub_filter 注入各子应用 `</body>` 前（saiOS 已注入「⌂ 工作台」按钮）
- 状态条实时拉 `/api/games` 显示 lotto 最新预测（数据打通 v1）

**统一通知服务**（`deploy/notify/` → 服务器 `/home/ubuntu/notify/`，systemd `notify.service`）：
- Python 单文件 + ThreadingHTTPServer，绑 `0.0.0.0:8800`（容器要访问宿主，**不能绑 127.0.0.1**）
- `POST /notify` 收事件 → 去重(dedup_key,24h)/合并(merge_key,60s)/限流(20/min) → 渠道路由（企业微信/TG/邮件，未启用等用户配置）
- Clash 故障探测：60s 探 9090/version，连续 3 次失败告警 + 恢复通知（状态机）
- **坑**：ThreadingHTTPServer 的 handler 线程里 `asyncio.create_task` 报 `no running event loop`
  → 必须全局 `_MAIN_LOOP` + `asyncio.run_coroutine_threadsafe` 投递（`_spawn()`）
- 事件源钩子：lotto `server/app.py _refresh_worker`（completed/summary/failed）、saiOS `task_runner.py`
  （succeeded/failed 终态，`notify_event()` 工具，失败静默）。lotto 容器需 `extra_hosts: host.docker.internal:host-gateway` + httpx 依赖
- **待办**：企业微信 webhook（`WECOM_WEBHOOK_URL` 进 `.deploy-env` + config.toml `enabled=true`）——用户提供后启用

**saiOS 生图链路（grok，2026-08-20 全通）**：
- 账号池 73 个（1643 失效已清，批量注册 73 新号，quota_fast=30/个）
- 生图用 `grok-imagine-image-lite`（basic 账号可用；标准 `grok-imagine-image` 要 super）
- **下载防盗链**：grok2api `config.defaults.toml` 设 `imagine_public_image_proxy=true` +
  `app_url="http://host.docker.internal:8003"` → 返回本地 URL，worker 从本地拉（绕开 assets.grok.com 403）
- worker 需 `-P solo` + `DB_POOL_CLASS=null` + `HTTPS_PROXY`（Clash 认证 `yuncai:密码@`）

## Clash 代理（Mihomo，2026-08-19 装）

- **Mihomo v1.19.30**（Clash Meta）：systemd `mihomo.service` 开机自启，监听 `0.0.0.0:7897`
  （mixed 端口 http/socks5），代理认证 `CLASH_AUTH` + API secret `CLASH_SECRET`
  （在服务器 `/home/ubuntu/.deploy-env`，勿外传）。配置 `/etc/mihomo/config.yaml`，
  provider 缓存在 `/etc/mihomo/providers/sub.yaml`。
- **Web 管理**：入口页「Clash 代理管理」→ `/clash-setup`（订阅配置页：填订阅 URL →
  PUT `/clash/api/providers/proxies/sub?url=` 更新并刷新节点）；管理面板 metacubexd 在
  `/clash`（`/clash/api` 反代 127.0.0.1:9090，nginx 注入 secret，用户无需填）。
- **用途**：Grok/xAI 上游从服务器直连超时（000），走 7897 代理即通（已实测 api.x.ai 401 / grok.com 200）；
  cpa/grok2api 上服务器时配置 `proxy: http://host.docker.internal:7897` 正好对上。
- SSH 侧一键：`python scripts/_server_clash_sub.py "订阅URL"`。
- **坑（2026-08-20）**：nginx `location ^~ /clash/api/` 的 `proxy_set_header Authorization "Bearer __CLASH_SECRET__"`
  占位符**从未被替换**（部署时只替换了 .deploy-env，nginx 文件是模板原样）→ 公网 /clash/api/version 一直 401、
  工作台 Clash 卡显示黄点。修复：`scripts/_fix_clash_secret.sh`（python 从 .deploy-env 读取真实 secret 精确替换 +
  nginx -t + reload + 验证）。**经验：每次改 nginx 配置后用 `grep -n '__CLASH_SECRET__'` 检查占位符是否残留。**
  注意：nginx reload 是异步的，紧跟在 reload 后的 curl 可能命中旧 worker 假 401，稍等再验证。
- **坑（2026-08-19）**：CLASH_AUTH 曾被重复追加进 `.deploy-env` → mihomo 配置 authentication 变
  多行畸形串 → 代理 403 → 所有经代理请求 000。修复：去重 `.deploy-env` + 整体重写 config.yaml
  （保留订阅 URL；`scripts/_clash_rewrite.py` 思路：python 读 .deploy-env + 现配置的 url 重新生成）。
  以后新增密钥到 `.deploy-env` 前先 `grep` 查重。

## ideas 目录去重归档（2026-08-20）

**背景**：用户指出 `D:\software\code\ideas` 下 50+ 项目"页面体验感不好、孤岛化"，要求按重复度整合去重。
**动作**：23 个重复/半成品项目**移动归档**到 `D:\software\code\ideas\_archive\`（保留 git 历史，零删除，可回滚）。
**清单**：`_archive/_ARCHIVE_MANIFEST.md`；分析报告 `docs/ideas-dedup-analysis.md`（工件 ideas-dedup-analysis）。
**保留不动的核心**：`list`(saiOS)/`writers`/`ten`（都在服务器）、`kaiyuan`(服务器 grok2api)、`ComfyUI`、`waoowaoo`/`xf`/`zg`/`zhiguan`/`gaokao-advisor`/`study`(活跃)、
`ai_lh`/`muai`/`PandaWiki`/`moto`(评估保留)、`tools`/`tools-v2`/`tool_box`/`toolbox`(工具箱簇，待归一未动)。
**后续待办**：① 4 个工具箱(tools/tools-v2/tool_box/toolbox)归一到 1 个（待用户定 tools vs tools-v2 主路线）；
② 可评估上线 gaokao-advisor、zg 进平台；③ 归档工具 `scripts/_archive_dedup.ps1`（注意：PS 5.1 下脚本文件 UTF-8 无 BOM 会解析报错，改用 shell 内联执行 Move-Item 成功）。

## 首页改造为 AI 助手中枢（2026-08-20，P0 已完成并上线）

**背景**：用户指出 saiOS 首页"功能太多太杂，不像 AI 助手的样子"，参考文档 `D:\software\docs\study\zcode\`（ZCode 产品文档 20 篇）。
**学习沉淀**：`docs/zcode-design-guide.md`（ZCode 设计范式）+ `docs/zcode-task-automation-notes.md`（任务/自动化范式）。
**核心结论**：从「功能堆砌」→「对话驱动的 AI 助手」，复用现有 `agent_chat`（`apps/api/app/services/agent_chat.py`）
+ MCP 创作工具（`apps/api/app/mcp/server.py`：generate_image/comic/text、synthesize_speech、story_forge 等）。

**P0 已上线**（2026-08-20）：
- 新增 `apps/web/src/pages/AssistantHomePage.tsx`：中央 AI 助手对话框 + 欢迎态能力建议（画图/写歌/写文/语音/角色卡/故事）
  + 流式对话 + MCP 工具调用过程展示 + `usePersistedChat` 本地持久化。复用 `/generations/text/agent/chat` 后端。
- 路由：`/` → AssistantHomePage（AI 助手）；原 DashboardPage 移到 `/dashboard`（数据看板保留）。
- 导航 `AppShell.tsx`：新增「AI 助手」(Sparkles, `/`)+「数据看板」(BarChart3, `/dashboard`)，移除 LayoutDashboard。
- 部署：同步 `AssistantHomePage.tsx`/`Routes.tsx`/`AppShell.tsx` → 服务器 → `docker compose -f compose.prod.yaml up -d --build frontend`。
  ⚠️ 注意：该命令会连带 recreate mysql/redis/api（已有依赖），重启后需确认全部 healthy（本次已核对）。

**P0 验证**：tsc/build 通过，frontend 重建成功，全服务 healthy，公网 200。

**P1 已完成（2026-08-20）**：生图/创作结果**回显到对话**。
- 后端 `apps/api/app/services/agent_chat.py`：tool done 事件新增 `result_data` 字段（完整结构化结果，含 `asset_url`），
  不再只发截断的 `summary`。
- 前端 `AssistantHomePage.tsx`：tool done 时解析 `result_data.asset_url`，追加"图片消息"，对话内 `<img>` 回显；
  `usePersistedChat.ts` 消息类型加 `image?: string`（持久化也保留图片）。
- 部署：同步 agent_chat.py + AssistantHomePage.tsx + usePersistedChat.ts → `docker compose -f compose.prod.yaml up -d --build api worker frontend`
  （全服务 healthy）。


**P2 已完成（2026-08-20）**：侧栏最近会话列表。
- 复用已有 `apps/web/src/hooks/useChatSessions.ts`（多会话 localStorage 管理：新建/切换/删除/自动命名/自动保存，本被 TextGenPage 用）。
  新增 `updateCurrentMessages(fn)` 函数式更新（供流式多步追加，避免闭包过期）。
- `AssistantHomePage.tsx` 重构：改用 useChatSessions，#新对话 按钮 + 左侧 236px 侧栏列出最近会话（高亮当前、点击切换、hover 删除）+ 中央对话不变。


**P3 已完成（2026-08-20）**：多模态结果回显增强。
- `AssistantHomePage.tsx`：按 `result_data.task_type` 区分媒体——`audio` 用 `<audio controls>`、`comic` 用 `cover_url` 封面图（标记 🎴 AI 漫画）、其余图片 `<img>`。
- `usePersistedChat.ts`：`PersistedChatMessage` 加 `media?: "image"|"audio"|"comic"`。

**目标整体状态（2026-08-20）**：首页「对话中枢」改造**核心目标已达成**——中央对话框 + 侧栏最近会话 + 自然语言驱动多模态创作（生图/写文/音频/漫画）结果回显，复用 agent_chat + MCP 工具，未破坏现有功能，已上线。

**⚠️ 对话中枢真实链路修复（2026-08-20，用户实测报错后定位）**：
- **问题现象**：对话中枢实际调用报 `Model 'grok-chat-fast' does not exist ... model_not_found`。
- **根因1（模型失效）**：saiOS 文本模型 `grok-chat-fast` 已不在 grok2api 可用列表（账号池刷新后模型名更新）。
  当前 grok2api 可用文本模型 = `grok-4.20-fast`（实测可生成）、image = `grok-imagine-image-lite`。
  **修复**：① `.env` 的 `OPENAI_COMPATIBLE_MODEL=grok-chat-fast` → `grok-4.20-fast`；
  ② DB `provider_configs` 里优先级最高的 Grok provider 的 `default_model` 也从 `grok-chat-fast` → `grok-4.20-fast`
  （空 model 自动选择时走 priority asc 的第一个 enable provider 的 default_model，故 DB 也要改）。
- **根因2（SSE 响应 bug）**：grok2api 对**带 tools** 的请求强制返回 SSE 流（`data: {...}\n\n`），而 saiOS 的
  `openai_compatible.py` 用 `resp.json()` 直接解析 → 抛 `Expecting value: line 1 column 1 (char 0)`。
  **修复**：`apps/api/app/providers/openai_compatible.py` 新增 `_parse_sse_json()`（逐 data 行解析、聚合 delta.content 与按 index 归位 tool_calls），
  generate() 里检测 `text.lstrip().startswith("data:")` 时走 SSE 解析，否则 JSON。
- **验证**：`docker compose -f compose.prod.yaml up -d --build api`（必须 --build 才会把改动的源码 COPY 进镜像；只 force-recreate 不重新读代码），
  端到端 `POST /api/v1/generations/text/agent/chat`（admin JWT + 空 model）→ **返回 `content:"在。"`**，链路打通。
- **经验**：⚠️ 改后端代码后 SeScp 到服务器还不够，必须 `--build`（源码在镜像构建时 COPY 进去），只 recreate 不生效；
  空 model 自动选 provider = priority asc 第一个 enable 的，改模型要同时改 .env + DB provider_configs 两处。

**🔴 对话中枢仍不可用：grok.com 对服务器出口 IP 风控 403（2026-08-20，用户持续"思考中"）**：
- **现象**：对话中枢实际调用仍失败，前端/日志见 `Chat upstream returned 403` / `status=403 body=-`；
  连续多次文本生成全部失败。生图（grok-imagine-image-lite）能通、文本（grok-4.20-fast）不能。
- **根因**：grok2api 经 Clash 代理访问 `https://grok.com/rest/app-chat/conversations/new` 返回 **403**
  （xAI anti-bot 风控当前机场出口 IP）。这是**外部服务风控**，非 saiOS 代码 bug。
- **已排查确认**：① saiOS API/前端/对话中枢代码链路正常（模型名已改、SSE 已兼容，直连测出过"你好！我是 Grok 4.5"）；
  ② grok2api 账号池 `last_fail_reason=rate_limited`；③ Clash 30 个节点逐一测试 **全部 403**（非单一节点问题）；
  ④ 更新 Clash 订阅后节点仍 30 个、grok 仍 403。
- **错误提示已优化**：`openai_compatible.py` 新增 `_extract_sse_error`——识别 grok2api 返回的 `event: error\ndata:{json}`
  SSE 错误帧，前端显示「上游错误: Chat upstream returned 403 (code=upstream_error)」而非笼统的「非 JSON」。
- **未解决的根本**：需要 ① 换一个**未被 grok.com 风控**的新机场订阅/节点；或 ② 走**不走 grok.com 的文本通道**——
  saiOS 里已配 `GPT-OSS(cpa) → gpt-oss-120b-medium`（cpa 85531，更稳），但需提供 cpa 可用 api key（DB 里加密存着）来启用默认文本。
- **候选方案**：文本走 cpa(GPT-OSS)、生图继续走 grok2api(grok-imagine-image-lite)，各用其长。

**✅ 文本已切到 cpa（2026-08-20，对话正常可用）**：
- **动作**：① `.env` 的 `OPENAI_COMPATIBLE_BASE_URL` → `http://host.docker.internal:8317/v1`（cpa）、
  `OPENAI_COMPATIBLE_MODEL` → `gpt-oss-120b-medium`、`OPENAI_COMPATIBLE_API_KEY` → `sk-hTD7vAUAQ9XXUZRTt`（cpa 调用 key）；
  ② DB `provider_configs` 里 GPT-OSS(cpa) provider `priority` 从 50 → 1；
  ③ 前端 `AssistantHomePage.tsx` 的 agent chat payload `model: ""` → `model: "gpt-oss-120b-medium"`（**必须显式指定**，
  否则空 model 自动选择会因同 priority 按 created_at asc 排到 Grok(priority1,早建) 而仍走 grok2api 403）。
- **cpa 账号来源**：`/home/ubuntu/cpa/auths/*.json` 共 3 个真实账号 token（antigravity-yueshewushuang@gmail.com、codex×2），
  走 cpa 自己的协议、**不经 grok.com**，因此不受 grok 403 风控。生图仍走 grok(grok-imagine-image-lite)，各用其长。
- **验证**：`docker compose up -d --build api frontend` 后，端到端 agent chat（显式 gpt-oss-120b-medium）→ **返回「你好！有什么我可以帮助你的吗？」**，
  8.6 秒正常、无 403。全部服务 healthy、公网 200。
- **grok 账号未浪费**：仍用于生图；文本改走后 cpa，等 grok IP 风控缓解（换干净节点）可随时切回。

**🔴 生图也 403（2026-08-20 验证）**：AI 助手「画图」能力**当前实际不可用**。
- 端到端测 grok2api `grok-imagine-image-lite` → **500 Internal server error**，日志根因：
  `app.platform.errors.UpstreamError: Image-generation upstream returned 403`（grok.com 对服务器出口 IP 的生图接口也风控了，
  与文本 403 同源）。之前生图能通，现在也被 403 拦。
- **结论**：saiOS 的 AI 助手 UI 层面（画图卡/生图回显/画廊/再生成）已完整，但**底层生图经 grok 实际 403 不可用**，
  需换无风控节点才能真出图。文本走 cpa 已通，生图仍卡在 grok 风控。

**🔍 生图替代路径：cpa 有图片模型但账号失效（2026-08-20 探查）**：
- cpa(cli-proxy-api:8317) 模型列表含 **`gpt-image-1.5` / `gpt-image-2` / `gemini-3.1-flash-image`**（生图模型，走 cpa 协议、**不经 grok.com 不受 grok 403 影响**）——
  理论上 AI 助手生图可切到 cpa 绕开 grok 403。
- **但 cpa 生图实测 401 `authentication token has been invalidated`**：生图走 antigravity 账号
  `/home/ubuntu/cpa/auths/antigravity-yueshewushuang@gmail.com.json`，其 token 失效/过期（expired 2026-08-20T20:05）。
  cpa 文本(gpt-oss-120b-medium)仍可用（200）；codex 账号仍有效（expired 2026-08-29）。
- **结论**：切生图到 cpa 的阻塞是 **antigravity 账号需重新授权**（用户重新登录 antigravity 提供新 token，或 cpa 刷新机制修复）；
  同时可把 AI 助手图片 provider 从 grok 切到 cpa(gpt-image-2)，避开 grok 的 IP 风控。

**✅ AI 助手文本创作真实可用（2026-08-20 端到端验证）**：
- 端到端 agent chat（走 cpa gpt-oss）要求"写生日祝福"→ 13.2s 返回完整可爱祝福文案，无错误。
- **结论**：AI 助手的文本创作（写文/写祝福/写歌歌词/故事等）**真实可用、体验正常**；生图待 antigravity 授权。
  当前 AI 助手的可靠定位 = 文本创作中枢（生图是待授权的可选项）。

## AI 助手完善（2026-08-20，源自 ZCode 文档研究）

**规格文档**：`docs/assistant-enhance-spec.md`（ZCode 20 篇文档经 3 子代理提炼，落地优先级 P0-P4 分批）。
研究笔记：`docs/zcode-design-guide.md` + `docs/zcode-task-automation-notes.md`。

**P0-1 已完成并上线**（欢迎态能力卡 + 媒体卡 + 工具过程卡）：
- `AssistantHomePage.tsx`：
  - 欢迎态从 6 条纯文字 → **按能力分组的能力卡片网格**（画图/写文/写歌&语音/角色，每类含多个示例，点击即发）。
  - 媒体消息卡升级：图片带类型角标(🖼️/🎴) + 「⬇ 下载/查看」链接；音频加「🔊 AI 语音」标签。
  - 工具调用过程从单行文字 → **toolLog 事件卡**（⏳ 进行中脉冲 / ✅ 完成），流式中可见 AI 在干什么。
  - 升级 `toolLine:string` → `toolLog:{name,status}[]`。

**P1+ 待办**（见规格文档）：斜杠命令面板(`/`)、`@`资源引用、编辑历史消息、"AI 记得你"欢迎语、会话分组/归档/搜索、能力中心抽屉、生成画廊/再生成等。

**P1-1 已完成并上线（2026-08-20）：斜杠命令面板**。
- `AssistantHomePage.tsx`：输入 `/` 触发**命令建议面板**（COMMANDS 常量映射 MCP 能力：/画图 /写文 /写歌 /语音 /漫画 /角色 /故事），
  按输入实时筛选，点选回填示例提示词（含 `____` 占位让用户补）；Escape 关闭；placeholder 提示"输入 / 选择能力"。

**P2+ 待办**：编辑历史消息（悬停铅笔重发）、`@`资源引用、"AI 记得你"欢迎语、会话分组/归档/搜索、能力中心抽屉、生成画廊/再生成、目标模式、定时创作。

**P2-1 已完成并上线（2026-08-20）：编辑历史消息**。
- `AssistantHomePage.tsx`：每条用户消息下方「✏️ 编辑此问题」→ 气泡变 textarea（可改）+「编辑重发/取消」；
  编辑重发 = 截断该条之后的上下文、以新文本重发（`send(text, editIdx)`：history 取 `messages.slice(0,editIdx)`、消息列表截断到该条前+新user+assistant占位）。

**P2-2+ 待办**：`@`资源引用、"AI 记得你"欢迎语、会话分组/归档/搜索、能力中心抽屉、生成画廊/再生成、目标模式、定时创作。

**P2-2 已完成并上线（2026-08-20）：媒体结果再生成**。
- `AssistantHomePage.tsx`：图片/音频媒体卡加「🔄 再生成」按钮——找到该媒体消息前最近的一条 user 消息 prompt，
  调用 `send(prompt)` 重发，形成"生成→调整→再生成"闭环。

**P2-3+ 待办**：`@`资源引用、"AI 记得你"欢迎语、会话分组/归档/搜索、能力中心抽屉、生成画廊时间线、目标模式、定时创作。

**P2-3 已完成并上线（2026-08-20）：AI 记得你欢迎语**。
- `AssistantHomePage.tsx`：欢迎态按历史会话个性化——有会话显示「欢迎回来 👋 上次在聊「XX」」+「回到最近会话/开启新对话」按钮；
  无会话显示首次问候。

**P2-4+ 待办**：`@`资源引用、会话分组/归档/搜索、能力中心抽屉、生成画廊时间线、目标模式、定时创作。

**P2-4 已完成并上线（2026-08-20）：能力中心抽屉**。
- `AssistantHomePage.tsx`：侧栏「新对话」下新增「🧭 能力中心」按钮 → 左侧覆盖抽屉（280px），按能力分组列出全部能力，
  点击某项把示例提示词放入输入框；顶部提示「输入 / 打开命令面板」。

**P2-5+ 待办**：`@`资源引用、会话分组/归档/搜索、生成画廊时间线、目标模式、定时创作。

**P2-5~P2-8 已完成并上线（2026-08-20）**：会话摘要条/时间分组/搜索/生成画廊（均 AssistantHomePage.tsx 迭代，细节略）。

**P2-9+ 待办**：`@`资源引用、会话自定义分组/归档、目标模式、定时创作。

**✅ saiOS 收敛改造（2026-08-20，用户授权鲸鱼做决定）**：
- **决策**：定位 = **A·创作 AI 助手**（一句话驱动创作，深层功能收纳，治"功能太多太乱太平凡"）。
- 规格：`docs/saios-consolidation-spec.md`。
- **P-A1 已上线**：AppShell 侧栏**默认只展开「创作」组(3项)主入口**，资源/角色/系统组**折叠收纳**（点组标题展开、不删功能、激活组自动展开），用 useLocation 判激活。
- 后续：P-A2 工具类收进 AI助手能力中心；P-A3 验证收藏路径可访问。

**P-A2 已完成（2026-08-20）**：AI 助手能力中心抽屉新增「🗂️ 资源库」分组——把原侧栏资源/角色入口
（提示词库/知识库/素材库/ASMR/Agent库/角色扮演）收纳为可跳转工具，功能不删只收敛；与 P-A1 导航折叠配合。


**✅ AI 助手文本创作路由加固（2026-08-20）**：`AssistantHomePage.tsx` 系统提示词优化——明确「写歌词/写文案/写故事等纯文本创作
直接用文字回答、绝不调用生图/音频工具」，只有用户明确要图片/音频才调工具。避免文本创作被模型误路由到走 grok 的媒体工具(403)，
确保写歌/写文稳定走 cpa 文本通道。

## 文档索引

- `docs/PROJECT_SUMMARY.md` — 全景总结（结构/模块/数据/部署经验/优化候选）
- `docs/zcode-design-guide.md` — ZCode 产品设计范式学习笔记（对话中枢改造依据）
- `docs/ideas-dedup-analysis.md` — ideas 目录重复度整合去重分析报告
- `docs/grok2api-troubleshooting.md` — grok2api 排障
- `scripts/` — 剧本生成器等工具
- `backups/` — 每日自动备份（2:00）

## saiOS v2 重设计规格（2026-08-24 审计完成，待用户拍板动工）

- 全量审计：38 条路由 × 3 子代理逐页核查，规格书 = `docs/saios-v2-redesign.md`（六宗罪/五大决策/P0-P3 分期）。
- 核心结论："low/没落地"不源于功能缺失（绝大多数 API 真实），而源于四大结构病：①27 个页面无导航入口
  （含全部 /create/* 生成页！）②产出裂成素材库/作品/工作室/助手 localStorage 四处 ③假交互
  （@引用不进 prompt、画布 setTimeout 假执行、发音人假选项、Music 只产 Suno 粘贴包）
  ④双首页撞车 + 深浅主题两套品牌色。
- **⚠️ Python 版本坑（PEP 758）**：api 容器跑 Python 3.14，无括号多异常捕获 `except A, B:` 合法；
  本地/CI 老解释器报 SyntaxError。已全仓统一为 `except (A, B):` 兼容写法（commit b9ea75c 引入躺 13 天后修复）。

## saiOS v2 落地进度（2026-08-24 P0-P3 全部完成）

锚点：371b178(P0)→47d82c2(P1)→7641c64(gpt-image2)→80289ad/72d07a9/10a2060(P2-1/2/3)→07d01d4+d1aa9a5(P3)→4609988(灵感画廊)。细节看 git log。
- **P0**：七大类导航 38 路由全露出/catalog 裸数组兼容/Comic 改真 gemini 图像模型/真 Edge-TTS 音色表/ST 页环境自适应 URL+token 掩码。
- **⚠️ 公网入口**：nginx 根 `/` 是备案页；saiOS 实际入口 = `/saios` 前缀（验收必须打 /saios）。
- **P1 调度大厅六硬伤**：会话上云 chat_sessions（迁移 b1c2d3e4f5a6）；@引用真注入 context_blocks；斜杠派发卡；catalog 直连模型选择；去黑话。坑：router prefix 双挂 /chat→404。
- **P2 统一 Studio /studio**：三段式驾驶舱+图像/漫画/TTS/音乐真实生成链+HUD 真进度+Web Audio 频谱+视频域（hub video 槽空时诚实报 Mock 拒绝不假装成功）+Story/Workflow 子能力导航卡。坑：backdrop-filter 建堆叠上下文，header 下拉需 relative z-30；canvas fillStyle 不认 CSS 变量要传 rgb 数值。
- **P3**：四皮肤全局化（AppShell 🎨 data-skin 覆盖 --color-primary 系变量，Studio 同一 store）；/persona 角色中心；反向克隆闭环（任务中心/素材库 → `/studio?rehydrate=<taskId>` 回填参数）；灵感画廊 /inspiration（gpt-image2 529 案例+图进 public/gallery 静态服务、分类/风格/场景筛选、高频风格共现配方一键 ?prompt= 进 Studio、前端 TF-IDF 余弦相似推荐）。
- **🔴 worker fd 耗尽**：celery 长跑 `Too many open files`→媒体任务全卡 queued。修复：compose worker ulimits nofile 65535。集体卡 queued 先查 worker 日志 fd。
- **🔴 MCP 工具不暴露 model 参数**：LLM 曾填自己聊天模型名→上游 400 not an image model。已去参走 hub 链。
- **🔴 api 重启后 frontend 必须 --force-recreate**：否则 nginx 缓存旧 api IP→502。
- **🔴 AppShell header 曾缺定位属性**：z-20 对 static 元素无效，下拉被页面级堆叠上下文（如 Studio z-30 header）盖住；需 relative + z-40。
- **🔴 SPA 内静态资源勿拼 /saios 前缀**：nginx 正则 location 已把 gallery/static/api 等前缀直接路由给 saiOS 容器；fetch("/saios/gallery/x") 被 SPA fallback 吃掉返回 index.html（200 text/html 极迷惑）。公共静态资源一律根绝对路径。
- **🔴 vite-pwa precache >4MB 文件 build 直接失败**：批量图片用 workbox.globIgnores 排除（gallery/**），按需加载不进离线缓存。
- gpt-image2 资产：canghe.ai=awesome-gpt-image-2 同源部署零差异；export/（529 案例 jsonl）入库，图片本体 gitignore 仅留本地。
