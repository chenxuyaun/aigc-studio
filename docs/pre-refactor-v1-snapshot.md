# Pre-Refactor-v1 快照

**Tag**: `pre-refactor-v1`
**Branch**: `refactor/v1`
**Commit**: d8d3ecd
**日期**: 2026-08-29

---

## 已跑通能力（重构期间任何阶段**不能丢失**）

| 能力 | 验证证据 |
|---|---|
| 5 槽 Model Center 调度 | 真实 5 次画图，worker 日志 `candidate=1/4` (d56dfba7) |
| 160 GPU 多模态 (FLUX/Wan/H3/MusicGen) | 真实调用，saios_flux_0000X.png 出图 |
| 智能路由 A (last_ok 过滤) | last_ok=0 → 跳 FLUX → 候选 3/3 成功（13.5s） |
| Asset URL 24h 签名 | 公网 curl 200 + 1.45MB PNG |
| 降级 model 替换 | `model=conf[2] or upstream` 3 处改完 |
| MCP server (stdio) | `generate_image` 等工具 |
| OpenAI-compatible 代理 | `/proxy/v1/chat/completions` (Model Hub 8511) |
| Storage 抽象 | `app/storage/base.py` 已定义接口 |
| Quark WebDAV | 二进制 + playwright 扫码登录跑通（host 内 8001） |
| Edge-TTS / MusicGen | 5 槽 audio + music |

---

## 当前 API 行为（不能改的接口契约）

### REST 端点（`/api/v1/`）
- `POST /auth/login` → JWT
- `POST /auth/refresh` → 新 token
- `GET /auth/me` → 当前用户
- `POST /generations/{image,video,audio,comic}/generate`
- `GET /generations/recent`
- `GET /tasks/{id}` → 任务状态
- `GET /assets/{id}/content?exp=&sig=` → 资源（24h 签名）
- `GET /assets/{id}/access-url` → 重签
- `GET /health/live`, `/health/ready`
- 等等

### MCP 工具（`mcp/server.py`）
- `generate_image(prompt: str) -> {asset_id, url, ...}`
- `generate_text(prompt: str, model: str = "") -> {content, ...}`
- `generate_comic(...)`, `synthesize_speech(...)`, `generate_video(...)`

### OpenAI 代理（Model Hub 8511）
- `POST /proxy/v1/chat/completions`
- `GET /proxy/v1/models`

---

## 环境变量模板（参考，敏感值已脱敏）

```env
# saiOS .env (关键配置)
DATABASE_URL=postgres://saios:***@127.0.0.1:3306/saios?sslmode=disable
REDIS_URL=redis://127.0.0.1:6379/0
JWT_ACCESS_TOKEN_MINUTES=120
JWT_REFRESH_TOKEN_DAYS=30
STORAGE_LOCAL_PATH=./storage
ASSET_SIGNED_TTL_SECONDS=86400
STORAGE_SIGNED_GET_TTL_SECONDS=3600
DEFAULT_TEXT_PROVIDER=gpt-oss-120b-medium
DEFAULT_IMAGE_PROVIDER=         # 故意清空, 走 hub 链 → FLUX
DEFAULT_VIDEO_PROVIDER=
DEFAULT_SPEECH_PROVIDER=edge_tts
PUBLIC_BASE_URL=http://124.221.130.64
AIGC_STUDIO_BASE_URL=http://127.0.0.1:8002
MODEL_HUB_BASE_URL=http://host.docker.internal:8511
MODEL_HUB_CACHE_SECONDS=10
```

---

## Docker Compose 路径（不重构）

- `apps/api/` → `aigc-studio-api-1`
- `apps/worker/` → `aigc-studio-worker-1`
- `apps/web/` → `aigc-studio-frontend-1`
- 端口映射、env_file、volumes **全部不动**
- compose.prod.yaml 是镜像构建依据，**不能改**

---

## 回滚方法

```bash
git checkout main
git branch -D refactor/v1
git checkout pre-refactor-v1
# 数据库无 schema 变更, 无需迁移
# 重启容器即可
docker restart aigc-studio-api-1 aigc-studio-worker-1
```

---

## P0 阶段约束（不破坏）

- ❌ 不删文件
- ❌ 不改 API 端点
- ❌ 不改 MCP 工具签名
- ❌ 不改 DB schema
- ❌ 不动 `migration/` 目录
- ❌ 不动 `compose.prod.yaml`
- ❌ 不动已跑通能力的实现逻辑（5 槽调度、FLUX、Asset 签名等）
- ❌ 不解 story_forge ↔ story_gate 循环依赖（留给 P4）
- ❌ 不进 P4（Domain）
- ❌ 不动 UI

✅ P0 唯一目标：建立 Core 不依赖 Domain 的清晰边界
✅ 第一批：把 task_runner.py 里的 Domain import 拆出去
