# AIGC Studio 演进路线图（2026-08-08）

> 基线：本地 11 容器全绿、git 已纳管、217+ 后端测试、15 个 GUI 冒烟、前端 22 组件测试、记忆闭环已验证、grok2api 失效已有 cpa 降级兜底、Linux 部署指南已就绪。
> 本文档只列**剩余方向**，按风险/收益排序。完成一项勾掉一项并记录日期。

## P0 底座风险（最优先，都是"单点失火"型）

1. **Git 远程仓库（当前最大单点）**
   - 现状：全部代码仅在 C 盘单副本；`.github/workflows/ci.yml` 存在但无远程、CI 从未真正跑过。
   - 动作：建私有远程（GitHub Private / Gitee 私有 / 局域网 Gitea），`git remote add` + 推送；随后 CI 自动激活（push 即跑 ruff/mypy/tsc/pytest/vitest）。
   - 验证：远程可见提交历史；CI 首跑全绿；再删本地任意文件能 clone 恢复。

2. **记忆数据未备份（数据完整性缺口）**
   - 现状：每日 2:00 备份只覆盖 MySQL + /app/storage；**tdai_data（L0-L3 记忆：对话/原子事实/画像）与 sillytavern_data 不在备份内**。
   - 动作：backup_tasks.py 增加 `docker run --rm -v tdai_data:/from -v ./backups:/to alpine tar -czf /to/<stamp>/tdai.tar.gz -C /from .`（worker 容器挂 volume 直读亦可）；sillytavern_data 同理；纳入保留 14 天策略。
   - 验证：备份产物含 tdai.tar.gz；删除测试记忆后能从 tar 恢复。

3. **恢复演练从未执行**
   - 备份未验证 = 没有备份。deploy/scripts/restore_drill.sh 已存在但无执行记录。
   - 动作：每月一次恢复到临时 MySQL 容器（端口 3307），抽表比对行数（asmr_works/prompts 计数一致即通过）。
   - 验证：演练日志留档 docs/，记录耗时与比对结果。

4. **C 盘磁盘水位（Docker Desktop 崩溃前科）**
   - 现状：vhdx 已 32G；C 盘曾到 90% 导致 Docker Desktop 崩溃。
   - 动作：每周 `docker builder prune -f` + `docker system prune -f`（排除数据卷）；把 Docker Desktop 数据目录迁到 D 盘（`wsl --shutdown` → 导出/导入 docker-desktop-data 到 D:\）；加磁盘水位告警（OpenClaw cron 每周检查 `Get-PSDrive C`，>85% 提醒）。
   - 验证：vhdx 体积稳定下降；连续 2 周无 90% 水位。

## P1 迁移与公网（SETUP.md 已备，剩下是执行）

5. **Linux 常开机迁移执行清单**
   - 按 deploy/linux-server/SETUP.md 走；补充切换 checklist：① 新机器先空跑（假数据）验证全链路 ② grok.com 连通性测试（不行就 cpa 降级）③ 数据迁移后行数比对 ④ 旧机保留 1 周只读 ⑤ 回滚方案 = 旧机随时可启。
   - 验证：新机器 11 容器全绿 + 旧数据完整 + 域名 HTTPS 可访问。

6. **域名 + HTTPS（Caddy）**
   - 买域名 → A 记录 → 改 deploy/cloud/Caddyfile → 起 caddy。迁移完成后弃用 cpolar 免费隧道（§12-3/8 随之关闭）。
   - 验证：https 访问、证书自动续期日志正常。

7. **端口入口统一（§12-4）**
   - 现状：API 宿主 8002 与 grok2api 8000 并存，文档/脚本需区分。
   - 动作：对外只暴露前端 5000（已是）；内部文档把 8002 标注为"仅本机调试"；可选把 grok2api 管理也收进 nginx 反代（/grok/ 路径）实现单端口入口。
   - 验证：外部只依赖 5000；8000/8002 可防火墙仅本机。

## P2 前端收尾（UI 方案剩余阶段）

8. **重点页原语应用扫尾**：Prompts/Roleplay/Story/ASMR/Assets/Tasks/生成页 统一 PageHeader + States 三件套 + Card hoverable + 数字 font-display（抽样审计逐页过）。
9. **深色补测回归**：tasks/create/knowledge/workflows 四页深色截图核对（审计脚本已备好 .cowork-temp/dark4.cjs，因登录限流偶发失败，重跑即可）。
10. **Workflow 画布拆分**：WorkflowCanvasEditor.tsx 63KB 单文件 → 拆节点/面板/连线模块，复用 Card/Button/Field 原语，替换 SkillNode/PromptNode 硬编码色。
11. **组件测试提至关键覆盖**：Dialog 焦点陷阱、ConfirmDialog、Toast、Select/Tabs 交互已测；补 Field 错误态、ErrorBoundary、usePrivateMediaUrl 缓存命中。CI 接入后设 vitest 覆盖率门槛。

## P3 可靠性增强

12. **LLM 网关自愈**：grok2api 会话失效已可降级 cpa；下一步——巡检发现失效时自动切 cpa + Toast/日志告警，恢复后自动切回（当前是手动/容错被动切换）。
13. **memory-core 锁自愈**：L1 锁死已修（重启清锁）；建议加锁超时自动释放（如锁龄 >30min 自动清），避免再次人工重启。
14. **调用量周报**：ai_call_log 已有数据；每周一汇总调用量/失败率/模型分布到巡检报告（dashboard 展示即可，无需外发）。

## P4 安全

15. **admin 初始密码确认**：若 INITIAL_ADMIN_PASSWORD 仍是出厂值，立即轮换（演示账号 brother1-3 已于 08-07 轮换）。
16. **.env 离线加密备份**：密钥仅存单机单文件；加密压缩包（7z AES-256）放移动盘/NAS，季度更新。
17. **SillyTavern 红线守护**：保持 8001 不公网；迁移 Linux 后默认防火墙不放行。
18. **依赖卫生**：每月 `pnpm outdated` + `uv pip audit`（或 pip-audit），高危 CVE 当周升级。

## P5 产品演进（可选，不阻塞）

19. **知识库检索质量**：当前本地 n-gram 哈希 embedding（512 维）匿名无外依赖但语义弱；可在有可用 embedding 服务时评估切换（保留本地兜底）。
20. **多端**：PWA 已装；如需推送通知（任务完成），接 Web Push（需 HTTPS 域名，P1 完成后解锁）。
21. **多用户配额**：兄弟账号增多后考虑每用户每日生成配额（RateLimit 中间件已有基础）。

---

**本周建议顺序**：1 → 2 → 3 → 4（全是底座风险，合计约 2-3 小时），再按迁移节奏进 P1。P2-P5 穿插进行。
