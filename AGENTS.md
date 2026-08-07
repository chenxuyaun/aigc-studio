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
```

## 当前状态（2026-08-07 更新）

**已完成的待办**（均含自动化测试）：
1. ✅ 前端 GUI 测试：`apps/web/e2e/`（global-setup 登录 + core-modules 4 测试 + smoke 5 测试，`--grep-invert @heavy` 跑默认套件）
2. ✅ 推理框架资料入库：知识库 `推理框架·vllm/ollama/llamacpp/selection` 4 篇
3. ✅ 连载告警：每日巡检 `serial_project_alerts`（`SERIAL_STALL_DAYS` 默认 7 天）+ Dashboard 高亮
4. ✅ 提示词库治理：清理 168 垃圾 + 382 重复（剩 13,464 条）；`content_hash` 去重机制已启用
5. ✅ 图片/视频生成真实链路修复（provider_configs 需含 grok-imagine-* 匹配行）
6. ✅ 图片生成页「从提示词库选择」入口

**注意**：
- E2E 登录态文件 `apps/web/e2e/.auth/` 含 token，已在 .gitignore
- 改后端代码后需 `docker compose up -d --build api worker`（容器内代码非热加载）
- MySQL 客户端操作必须带 `--default-character-set=utf8mb4`（否则中文条件匹配失败）

## 文档索引

- `docs/PROJECT_SUMMARY.md` — 全景总结（结构/模块/数据/部署经验/优化候选）
- `docs/grok2api-troubleshooting.md` — grok2api 排障
- `scripts/` — 剧本生成器等工具
- `backups/` — 每日自动备份（2:00）
