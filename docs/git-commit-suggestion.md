# Git 提交固化建议（AI 助手完善 P0-P2 + 文本链路，2026-08-20）

> 背景：`git status` 显示 23 个已修改 + 284 个未跟踪文件。这些轮（AI 助手 13 项增强 + 文本链路 cpa 切换 + 修复）的核心代码改动
> **当前仅存在于工作区，尚未 git 提交**。本清单供审批提交时参考，明确「该提交 / 不该提交」边界。

## 一、✅ 值得提交固化的核心改动（本轮成果）

### 后端（文本链路修复 + 通知）
- `apps/api/app/providers/openai_compatible.py`（+103：SSE 兼容 `_parse_sse_json` + 错误友好 `_extract_sse_error`）
- `apps/api/app/services/agent_chat.py`（+13：tool 事件带 `result_data`，媒体回显）
- `apps/api/app/core/config.py`（+10：NOTIFY/AUTO_LOGIN 配置项）
- `apps/api/app/services/task_runner.py`（+43：生成完成/失败通知钩子）

### 前端（AI 助手 13 项增强）
- `apps/web/src/pages/AssistantHomePage.tsx`（**新增 783 行**：AI 助手对话中枢）
- `apps/web/src/components/layout/AppShell.tsx`（导航：AI 助手 + 数据看板）
- `apps/web/src/microfrontend/Routes.tsx`（`/`→助手、`/dashboard`→看板）
- `apps/web/src/hooks/useChatSessions.ts`（多会话）
- `apps/web/src/hooks/usePersistedChat.ts`（媒体消息字段）

### 文档 / 工件 / 部署
- `docs/assistant-enhance-spec.md`、`docs/zcode-design-guide.md`、`docs/zcode-task-automation-notes.md`、`docs/ideas-dedup-analysis.md`
- `artifacts/`（19 个版本化工件，每个含 SHA-256 + provenance）
- `deploy/yuncai-site/*`（统一工作台 + svc 落地页 + notify）

## 二、⚠️ 绝不提交（敏感/无关）
- `.server-keys/id_ed25519*` —— **SSH 私钥，必须忽略，绝不入库**
- `.env` / `.deploy-*.tar` / `*.db` —— 含密钥 / 凭据 / 数据库
- `.build-tmp/migrate/*`、`.deploy-*.tar` —— 迁移备份（本地临时）
- `wrea/` —— 另一独立项目，不应混入本仓库提交

## 三、🟡 视需要提交（部署脚本，可选）
- `scripts/_server_*.py`、`scripts/_server_sync*.py` 等部署脚本（此前已在用，可随核心一起或单独提交）

## 建议提交方式
- 分 2 条提交，信息清晰：
  1. `feat(saios): AI 助手对话中枢 + 文本链路切 cpa（P0-P2，13 项增强）`（后端 + 前端 + docs/artifacts/deploy）
  2. `chore: 忽略 .server-keys/.env 等敏感文件`（若无 .gitignore 则先补，防止私钥入库）
- 提交需用户审批后执行。

> ⚠️ 重要：提交前务必确认 `.server-keys/`（SSH 私钥）已加入 `.gitignore` 或被显式排除，**任何情况下都不能把私钥提交进 git**。
