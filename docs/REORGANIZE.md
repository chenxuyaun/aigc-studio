# AIGC Studio 重构规划（2026-08-10）

> 背景：多轮迭代后功能膨胀，存在重复实现、入口分散、孤儿功能。本规划基于全站盘点
> （前端 39 页面 + 后端 222 端点），按「用户可见」与「实现层」两类问题给出分阶段方案。
> 原则：小步重构，每阶段测试全绿 + 可独立部署；不动核心链路行为。

## 一、现状问题清单

### A. 用户可见（功能/入口混乱）
| # | 问题 | 位置 |
|---|---|---|
| A1 | 音乐圆桌双实现：通用 RoundtablePanel（6 页复用）vs MusicGenPage 内联副本 ~350 行 | `components/creation/RoundtablePanel.tsx` vs `pages/MusicGenPage.tsx` |
| A2 | 创作入口清单 4-5 处硬编码（新增工具页要同步改多处） | CreatePage / DashboardPage / TasksPage / PromptsPage |
| A3 | 4 个孤儿路由（无导航无链接）：Agent 目录 / 工作流 / 技能库 / 技能对话 | `/agent-directory` `/workflows` `/skills` |
| A4 | 「我的创作」7 页并存，WorksPage 与 StoryStudioPage（/story/projects 双入口）、AssetsPage 与 AsmrPage 数据域重叠 | Works/Assets/Tasks/ASMR/Story/Roleplay/Search |
| A5 | 知识库素材注入 3 套前端实现 + 2 套后端接口 | TextGenPage 显式选择 / RoundtablePanel 自动注入 / MusicGenPage 内联 |
| A6 | 5 套聊天引擎并存 | useChatSessions / usePersistedChat×2 / 本地 state / useRoleplayEngine |
| A7 | 音乐分享链接 2 处重复拼 URL | WorksPage.tsx:269 / MusicGenPage.tsx:870 |
| A8 | PhotographyPage 双挂载（独立路由 + AssetsPage 内嵌 Tab） | AssetsPage.tsx:10,249 |
| A9 | 无音乐作品详情页（只能在 WorksPage 内嵌对比） | — |

### B. 实现层（代码重复，维护成本）
| # | 问题 | 位置 |
|---|---|---|
| B1 | `_result_text` 5 份逐字相同 | creation_service / director_assistant / music_assistant / knowledge_materials / roundtable_service |
| B2 | `_extract_json` 4 份 + 内联 JSON 解析 3 处 | creation_service / music.py / roundtable_service / character_distill / knowledge_materials×3 |
| B3 | `_load_json` 4 份相同 | memory_inject / roleplay / story_forge / api/v1/memory |
| B4 | SSE 事件格式化 3 份 | roundtable_service / music.py / story.py + text.py |
| B5 | 素材文案 4-5 种叫法（知识库素材/联网资料/参考资料…） | roundtable_service / music.py×3 / story_forge |
| B6 | 质检 3 套 + 自检重写闭环 2 处同构 | ai_voice_checker / _validate_lyrics / _validate_final；music.py vs roundtable_service |
| B7 | 素材检索 3 入口：`/ask` 自带一套检索循环 vs `_retrieve_kb_hits` | knowledge.py:144-200 vs knowledge_materials.py:169 |
| B8 | 任务状态机 4 套 + stale 恢复 2 份 | task_runner / generation_service / story_tasks / 手写落库（story.py:422 / upstream.py:220） |
| B9 | 记忆配置读取 2 份 + 检索循环局部重复 | memory_inject.py:43 / api/v1/memory.py:55 |

## 二、目标信息架构（导航建议）

```
工作台（首页：速览+入口地图）
├─ AI 创作（/create：11 工具卡片）
├─ 我的创作（合并：音乐作品 + 群演作品 + 创作项目入口 + 创作群）
├─ 角色扮演（聊天 + 面板 + SillyTavern 引导入口）
├─ 提示词库
├─ Agent 库（+「技能」「工作流」「Agent 目录」三个平级入口，补孤儿导航）
├─ 知识库
├─ 任务中心
├─ 素材库 / ASMR 库
└─ 设置（模型/用户/日志/上游）
```

## 三、分阶段实施

### 阶段 1：后端纯重构 ✅ 已部署
- [x] B1-B4：`services/text_utils.py`（result_text / extract_json / load_json / sse_event）收敛 5+4+4+3 份重复
- [x] B5：素材块文案统一进 `knowledge_materials.format_material_block()`（music 圆桌/discuss/followup/通用圆桌 4 处）
- [x] B7：`/ask` 复用 `retrieve_kb_chunks`（与创作检索共用底层）
- 验证：309 全绿已部署

### 阶段 2：前端入口统一 ✅ 已部署
- [x] A2：`shared/createTools.ts` 共享工具清单（CreatePage 11 工具 / DashboardPage 快捷 6 / TasksPage 新建 4，一处维护）
- [x] A7：`lib/share.ts` 统一分享链接（WorksPage + MusicGenPage）
- [x] A3：Agent 库页加「技能库/工作流/Agent 目录」入口（孤儿路由全部可访问）
- 验证：tsc 通过已部署

### 阶段 3：圆桌统一 ✅（B6/B8 评估后保持现状）
- [x] A1：`MusicRoundtablePanel` 组件抽取（MusicGenPage 976→464 行；组件保留作品入库/和弦/追问/送 1对1；incomingTheme/incomingStyle 预填联动）——实弹冒烟通过
- [ ] B6：validate-and-rewrite 抽公共——评估：两处 validate 语义不同（歌词 vs 通用），强行统一负优化，保持现状
- [ ] B8：任务创建统一——评估：story/upstream 任务语义与媒体任务不同，保持现状

### 阶段 4（可选）：聚合与详情 ✅ 完成
- [x] A8：AssetsPage 写真 Tab 改为跳转独立 /photography（消除双挂载）
- [x] A9：音乐作品详情 Dialog（完整歌词/和弦/编曲/Suno 风格/标签/分享/发布/删除）
- [x] A4：WorksPage 群演作品区加「查看全部项目 →」跳 /story
- [x] A6：评估后保持现状——useChatSessions 已复用 usePersistedChat 类型（多会话 vs 单会话语义不同）；MusicGen discuss 本地 state / useRoleplayEngine 均为业务专属，强合并负优化
