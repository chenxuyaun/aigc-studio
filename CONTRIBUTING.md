# 贡献指南

感谢你愿意为 AIGC Studio 贡献代码！请先阅读 [AGENTS.md](AGENTS.md)（接手引导）与
[docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md)（全景）。

## 环境准备

- 后端：Python ≥3.14（建议 uv），`cd apps/api && uv sync && alembic upgrade head`
- 前端：Node 20 + pnpm，`cd apps/web && pnpm install && pnpm dev`

## 开发规范

- **红线**：`.env` 密钥绝不提交/打印；公网只暴露 5000；不开放匿名注册
- 后端改动必须跑：`cd apps/api && uv run pytest`（全量必须绿）
- 前端改动必须跑：`cd apps/web && npx tsc --noEmit`
- 新功能尽量走 Mission Orchestrator 的可调度单元（`mission_service._KIND_LABELS`），
  而不是在页面堆按钮——平台正在向「一个目标框驱动」收敛
- 提交信息用中文/英文均可，描述清楚「改了什么、为什么」

## 提交 PR 前检查

1. `uv run pytest` 全绿
2. `npx tsc --noEmit` 通过
3. 没有在代码/脚本里硬编码任何密码或 token
4. 没有把 `.env`、备份、第三方克隆目录提交进仓库

## 结构速览

```
apps/web        React 19 + Vite（页面在 src/pages/）
apps/api        FastAPI + SQLAlchemy async（路由 app/api/v1/，服务 app/services/）
packages/shared-types  前后端共享类型
docs/           规划与设计文档（REORGANIZE.md / AGI_HARNESS.md / PROJECT_SUMMARY.md）
```
