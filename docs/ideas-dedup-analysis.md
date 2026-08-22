# ideas 目录重复度整合去重分析报告

> 扫描时间：2026-08-20
> 扫描范围：`D:\software\code\ideas` 全部 50+ 项目
> 判断依据：README 定位、技术栈、git 活跃度、是否已在服务器平台运行

## 总览

- 服务器「平台」已上线 14 容器 + 6 systemd 服务（工作台 13 卡）：
  saiOS(list)/writers/ten/soul/ai/memory/searxng/silly/lotto/grok/cpa/clash/notify
- ideas 目录 50+ 项目，多数为**学习草稿、半成品、或互相重叠的同类项目**
- 按重复度聚成 6 大簇，下面逐簇给出「保留主推 / 归档合并 / 理由」

---

## 簇① 内容创作 / 写作平台（最高重复度，8+ 项目）

**主推：`writers`（写作中台，已上线服务器，持续活跃）** — Go 单二进制 + PostgreSQL，
面向中文网文"百万字不崩"，有确定性 A 闸 + LLM B 闸 + 账本留痕，是目前最成熟、唯一在线的写作产品。

**建议归档/合并：**
| 项目 | 定位 | 活跃度 | 处置 |
|---|---|---|---|
| `wirter` | 五阶段成长写作系统(infant→elder)，PyTorch 训练 | 2026-02 冻结 | 归档（构思原型，已被 writers 工程化取代） |
| `novel` | Manuskript + NovelForge 双套写作文档工具 | 2026-04 | 归档（功能子集，FastAPI+Vue 半成品） |
| `novel-workspace` | 多模态+长期规划 AI 系统骨架 | 2026-06 | 归档（研究型骨架，非产品） |
| `prds` | AI Content Workflow MVP（Next.js） | 2026-04 | 归档（AI 内容生产 MVP 雏形） |
| `creator` | 多模态创作 hub skeleton | 2026-05 | 归档（阶段化 MVP，未完成） |
| `acgic` | Rust 控制面 + Python 动画创作脚手架 | 2026-03 | 归档（Rust 脚手架 M1） |
| `ai_flow` | 端到端创意生成管线 | 2026-03 | 归档（管线演示） |
| `ai_dream_painter` | AI 绘画小程序 | 2026-06 | 归档（微信小程序，功能单薄） |

**注**：`list` 内部还藏了 `Codex-Dream-Skin`(创作皮肤)、`happy-code` 等小项目，可一并评估。

---

## 簇② 工具箱平台（4 个几乎同类 + 1 个 V2）

**主推：`tools`（Web Toolbox & Novel Studio All-in-One，React+FastAPI+PG+MinIO）**
或 **`tools-v2`（Next.js15+FastAPI+LangGraph，技术最新）**

**建议合并：**
| 项目 | 定位 | 活跃度 | 处置 |
|---|---|---|---|
| `toolbox` | Web 工具箱（文档转换/PDF/AI 写作） | 2026-02 冻结 | 并入 tools（功能重复度高） |
| `tool_box` | Windows 桌面 AI Toolbox（Tauri） | 2026-06 | 独立形态（桌面端），暂留或并入 |
| `tools-v2` | 下一代 AI 写作助手全栈 | 2026-02 | 与 tools 合并——若走 Next.js 路线以它为主 |

> 4 个"工具箱"目的一致（文档处理+AI 写作+任务），应归一到 1 个。

---

## 簇③ 博客 / 知识库（5+ 项目）

**主推：`PandaWiki`（带官网/微信生态的知识库，最完整）**

**建议归档：**
| 项目 | 处置 |
|---|---|
| `private_blog` | 归档（React 模板起步，内容少） |
| `self-blog` | 归档（Next.js create-next-app 起步，未填充） |
| `blog-notes` | 归档（笔记型仓库，2026-03 冻结） |
| `dreams` | 归档（个人知识花园原型，2026-07） |
| `learning-journey` | 归档（学习记录仓库） |

---

## 簇④ 量化交易（4 个 + 1 个已在服务器）

**主推：`ten`（AI Trading Desk，已上线服务器，持续活跃，94 个 API 路由）**

**建议归档：**
| 项目 | 处置 |
|---|---|
| `lhpt` | 归档（Local AI Quant Pipeline P1 数据层，2026-06） |
| `ai_lh` | 评估（AlphaEdge 量化，2026-08 仍活跃，若功能超出 ten 再保留） |
| `ashare-quant-strategies` | 归档为资料（A股量化策略研究库，文章型） |
| `small_model_distributed...` | 归档（分布式认知 agent 需求文档） |

---

## 簇⑤ AI 系统 / 自我意识研究（4+ 项目，多为实验）

**主推：`muai`（自我意识 AI，含 dashboard + mm_orch 编排）** 或 `study`(mm_orch MVP)

**建议归档：**
| 项目 | 处置 |
|---|---|
| `spiritual_realm_projects` | 归档（MuAI 多模型编排早期版，2026-01，被 muai 取代） |
| `local-ai` / `localai` | 归档（本地 RAG 工作台，Open WebUI 封装，功能被 saiOS 覆盖） |
| `llm_ai` | 归档（多模态规划 baseline，2026-03） |
| `hello-agents` | 归档（agent 学习项目） |

---

## 簇⑥ 垂直/独立（不重复，各自保留或单独评估）

| 项目 | 定位 | 建议 |
|---|---|---|
| `gaokao-advisor` | 高考志愿 AI 助手（2026-07 活跃） | 可独立上线或并入平台 |
| `zg` / `zhiguan` | 中文微练习（私密冥想） | 保留（2026-07 活跃） |
| `xf` | 纸片拼贴视频流水线（Remotion，2026-07） | 保留（独特能力） |
| `kaiyuan` | 内含 grok2api/grok-register（2026-07） | **已在服务器（grok2api 就是它）** |
| `TypoDiffusion` | 中文文字去噪实验 | 归档（研究） |
| `daxiangbizhi` | Rust post-PyTorch 原型 | 归档（实验） |
| `waoowaoo` | AI 影视创作（有在线站） | 独立产品，单独评估 |
| `ComfyUI` | ComfyUI 本体（第三方） | 保留（第三方依赖） |
| `moto` / `openflow` / `codex-app-transfer` / `studys` 等 | 各类工具/学习 | 逐个按需 |

---

## 建议的整合动作（待用户确认后执行）

1. **归档合并（移动到 backups/archive/，不删除）**：约 20+ 半成品/重复项目，
   把磁盘从碎片化变为整洁，同时保留历史
2. **归一 4 个工具箱为 1 个**：确定 tools vs tools-v2 主路线
3. **归一写作类为 writers**：其余写作原型归档
4. **评估可上线 2 个**：gaokao-advisor、zg（若用户想要）
5. **平台接入**：确认后把在线的（ten/writers/saiOS 已在）之外的新服务接入工作台

> ⚠️ 所有动作都是**归档（移动备份）而非删除**，零数据丢失风险。
