# CC Switch × Cherry Studio 功能对齐盘点（模型中心 Parity 路线图）

> 目标（goal-894e02ee）：把 CC Switch 和 Cherry Studio 的全部功能加进模型中心，然后规划删除冗余。
> 本文档 = 权威差距清单。每轮推进后更新状态。图例：✅已有 ｜ 🟡部分 ｜ ❌缺失 ｜ ➖不适用（有更优替代）

## 一、CC Switch（Claude Code / Codex 供应商切换器）

参考：[alhza/cc-switch](https://github.com/alhza/cc-switch)、[kongkongyo/cc-switch](https://github.com/kongkongyo/cc-switch)

| CC Switch 功能 | 模型中心现状 | 状态 | 备注 |
|---|---|---|---|
| 多供应商 CRUD + 密钥管理 | providers 表 + UI 卡片编辑 | ✅ | |
| 一键切换激活供应商 | 单槽 promote / 全局切换（带确认） | ✅ | v3 链语义更强 |
| 配置导入/导出/备份 | ⬇导出/⬆导入（version 3 含链+prompts） | ✅ | 缺自动定时备份 🟡→见下 |
| 配置校验/连通测试 | 🩺 连通检测 | ✅ | |
| 与本机配置冲突检测 | 🧪 冲突检测（对照 saiOS .env） | ✅ | CC Switch 独有的"防串台"思想已有 |
| 多工具配置文件管理（settings.json/auth.json 直写） | ➖ | ➖ | 我们是网关模式（/proxy/v1），不需要直写各工具配置文件 |
| 系统托盘快捷切换 | ➖ | ➖ | 服务端无托盘；UI 状态条即等价物 |
| 供应商分组/置顶 | 分组标签过滤 + priority 拖拽 | ✅ | |

## 二、Cherry Studio

参考：[Cherry Studio 文档](https://docs.cherryai.com.cn.cn/)、[官网](https://cherrystudiocn.com/index.html)

| Cherry Studio 功能 | 模型中心现状 | 状态 | 备注/计划 |
|---|---|---|---|
| 多供应商管理（内置目录） | 内置目录 + 自定义 | ✅ | |
| 按能力分槽（对话/绘图/…） | 五槽 v2 | ✅ | |
| 故障转移 | **v3 候选链（超越 Cherry）** | ✅ | |
| 模型列表拉取 | 🔍 获取（+zarklab 等预设兜底） | ✅ | |
| 模型管理（置顶/隐藏/别名） | ❌ | **R2** | per-provider 模型 curation 表 |
| API Key 余额/额度显示 | ❌ | **R1（本轮）** | OpenRouter /api/v1/key 可查余额；cpa 本地无额度概念 |
| 数据统计（用量/费用图表） | 🟡 by_model + by_day 柱状 | **R1（本轮增强）** | 缺：按供应商维度、费用估算、时间范围选择 |
| 助手/提示词预设 | Prompts 表（激活制） | 🟡 | 缺变量占位符、按槽位绑定模型 |
| 知识库/RAG | ➖ saiOS 已有知识库模块 | ➖ | 不在 hub 重复建设 |
| 话题/会话管理 | ➖ saiOS 对话中枢已有 | ➖ | |
| MCP 支持 | ➖ saiOS 已有 MCP server | ➖ | |
| 备份到 WebDAV/S3 | ❌（仅手动导出） | **R3** | 服务器本地定时快照即可 |
| TTS/ASR 配置 | audio 槽 Edge-TTS 已接 | ✅ | ASR 未接（暂无免费源） |
| 翻译/绘画等内置应用 | ➖ saiOS 场景覆盖 | ➖ | |
| 模型价格/费用显示 | ❌ | R4 | 结合用量统计估算成本 |

## 三、执行顺序（后续轮次按此推进）

- **R1（本轮）**：① OpenRouter 余额查询 + UI 显示；② 用量统计加"按供应商"维度
- **R2**：模型 curation（置顶/隐藏/别名），供 🔍获取 后管理
- **R3**：自动备份（服务器本地快照 + 保留 N 份）
- **R4**：费用估算（结合 OpenRouter pricing）
- **删除规划**：以上完成后，盘点 saiOS 侧旧 `provider_configs` DB 通道与 hub 的重复度，
  输出 `docs/deprecation-plan.md`（哪些旧通道可删、迁移步骤、回滚方案），经用户确认后再动手。

## 变更记录

- 2026-08-22 R1 ✅：文档创建；① `GET /api/providers/{id}/balance`（OpenRouter 实测：已用 $0.163，
  无限额度）+ 卡片 💰 按钮；② 用量统计加"按供应商分布"维度（实测 4 行数据）；
  ③ 配套修复：MySQL 补发布 `127.0.0.1:3307`（仅回环，hub 的 SAIOS_DB_URL 依赖它）。
- 2026-08-22 R2 ✅：模型 curation 上线——新表 `provider_models` + `GET/PUT
  /api/providers/{id}/models/curated`；模型选择列表支持 ⭐置顶优先 / 🚫隐藏置灰沉底 /
  ✏️别名显示，行内按钮即时持久化（实测保存→读回→导出 v4 含 curated 全通）。
  附带：**model-hub-guard 自愈守卫上线**（systemd timer 每分钟检查 8511 监听进程，
  非 172.17.0.1 正版即杀+重启；首跑即捕获第四次 0.0.0.0 僵尸）。
- 2026-08-22 R3 ✅：自动备份快照上线——`model-hub-backup.timer` 每日 03:40 跑
  `/home/ubuntu/model-hub/backup.sh`：export JSON（含密钥/链/curation，坏快照自动丢弃）
  + sqlite 文件兜底，保留 14 份。首跑实测：hub-20260822-152945.json 6830B
  （11 providers + 5 chains + 2 curated）+ db 快照。
- 2026-08-22 R4-lite ✅：用量统计顶部显示 OpenRouter 真实花费（"💰 已用 $x（剩余/无限额度）"），
  实测 UI 已含该文案、代理 chat 仍通（"稳"）。深度按模型计费估算**暂缓**
  （未记录 token 数；真实花费已可见，满足"没钱"关切）。
- **下一步 → 删除规划**：✅ 已完成——`docs/deprecation-plan.md`（三通道盘点、9 个代码点
  下线清单、P1/P2/P3 分阶段 + 回滚方案 + 验收指标），执行待用户逐阶段确认。
