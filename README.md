# AIGC Studio

AI 创作工作台：文本 / 图片 / 视频 / 语音生成，配套提示词库、Agent、技能、工作流、写真摄影与素材管理。

Monorepo：`apps/web`（React 19 + Vite + Module Federation）、`apps/api`（FastAPI + SQLAlchemy async）、`packages/shared-types`。

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
