# 01 · 项目审计报告（PROJECT ARCHITECTURE AUDIT）

> 版本：v1.0 ｜ 审计日期：2026-08 ｜ 审计范围：故事创作全链路（story_forge / story_crew / creation_service / roundtable_service / roleplay / MCP 创作工具 / 前端创作页 / 测试）
> 原则：只读审计，未修改任何代码。

---

## 1. 审计结论摘要（TL;DR）

当前系统是一个**功能完备但缺乏"创作智能内核"的生成器**：

- 它有完整的**工程链路**（项目/章节/版本 CRUD、任务化、连载调度、流式生成、导出 EPUB），
- 但它的**创作决策链路**是一条「Prompt → Scene」的单次生成路径：一次 LLM 调用即产出定稿，
  没有人物模型、没有价值模型、没有动机追踪、没有因果图、没有故事状态机、没有质量门、没有修复循环。

一句话总结：

> **系统有"写"的能力，没有"想"的能力；有"产"的能力，没有"判"的能力。**

对照《创作智能内核升级需求》的核心检查项（A-O）：

| 检查项 | 现状 | 证据 |
|---|---|---|
| A. 主题→直接生成故事 | ⚠️ 部分存在 | `creation_service.script_project`：主题+选角 → 一次性分幕大纲；`generate_chapter_script`：场景 → 对话流直接出章 |
| B. Character Model | ❌ 缺失 | `StoryCharacter` 仅 name/role/description/goals/arc/current_state/skill_ids（全部 Text 字符串） |
| C. Character Value Model | ❌ 缺失 | 全库搜无 value_hierarchy / core_values / beliefs 概念 |
| D. Character State | ⚠️ 雏形 | `current_state` 是**字符串**（stagehand 每章后覆盖写入），非状态机，无状态迁移约束 |
| E. Motivation Trace | ❌ 缺失 | 无任何动机链数据结构；行为只存在于正文文本里 |
| F. Causal Graph | ❌ 缺失 | 无事件因果结构；「前章回放」只是大纲字符串拼接 |
| G. Story State | ❌ 缺失 | `story_project.settings` 是 JSON 垃圾桶（compass/writing_style/summary/direction/consistency_report/knowledge_doc_ids 全塞里面）；无 world_state/timeline/open_loops/causal_graph |
| H. Generation Gate | ❌ 缺失 | 生成后直接 `status="done"` 落库，无门禁 |
| I. 独立 Critic | ❌ 缺失 | `story_crew.editor` 是**同一模型扮演**的 prompt 角色，输出审校报告存 `notes["review"]`，不触发任何修复 |
| J. Repair Agent | ❌ 缺失 | editor 给建议，人手动改；无自动局部修复 |
| K. 单 LLM 生成+评价 | ✅ 是 | 全链路 `resolve_text_provider` 单模型（grok-chat-fast 默认）；writer/critic/director 同模型 |
| L. 文笔好=故事好 | ✅ 是 | 唯一「质量」机制是写作特征池（文笔层）+ 创作罗盘（承诺层）；无故事成立性度量 |
| M. 情绪强烈=人物深刻 | ✅ 是 | `stagehand` 只更新情绪/处境字符串；无情绪捷径检测、无人物深度验证 |
| N. 主题表达明显=主题深刻 | ✅ 是 | 无 Theme Guard；无主题入侵检测 |
| O. Prompt 形容词依赖 | ✅ 是 | 「人物言行与性格一致」「自然流畅」「严禁重复」「有完整的起承转合」等均为软约束形容词 |

**验收判定**：需求三十（最终验收标准）18 项中，当前系统只天然满足 0 项（全部 18 项均需架构改造，无一具备）。

---

## 2. 当前架构（实测）

### 2.1 技术栈与运行形态

```
前端 React19/Vite/ModuleFed (apps/web, 34 页)  ──►  nginx :5000 ──►  FastAPI :8002
                                                                    │
                          ┌─────────────────────────────────────────┤
                          ▼                                         ▼
               MemoryCore :8420（角色陪伴记忆 L0-L3）      MySQL 8.4（44 表）
                          │                                         ▲
                          ▼                                         │
               grok2api :8000（OpenAI 兼容，grok-chat-fast）◄── Celery/Redis（text/image/video/audio/import/maintenance）
```

### 2.2 故事创作模块地图（本次审计焦点）

```
页面层  apps/web/src/pages/
├─ StoryProjectPage.tsx / StoryStudioPage.tsx + storystudio/{ChapterEditor,CompassPanel,
│   CrewPanel,WritingStylePanel,SerialPanel,SearchPanel,...}
└─ CreationPage.tsx（AI 导演工作室）

路由层  apps/api/app/api/v1/
├─ story.py     32 端点：projects/chapters/characters/schedules/compass/writing-style/crew/outline/search/export
└─ creation.py   5 端点：plan / script / review / publish / setup

服务层  apps/api/app/services/
├─ story_forge.py        (1461 行) 项目/章节/角色 CRUD + 叙事生成 + 剧本生成 + 大纲 + 修订 + 导出
├─ story_crew.py         (199 行)  director / writer / editor / stagehand / consistency 五阶段
├─ creation_service.py   (558 行)  主题→选角→剧本→建群（AI 导演工作室）
├─ director_assistant.py (167 行)  群聊 @AI 导演 指令
├─ roundtable_service.py (495 行)  通用创作圆桌（多角色讨论 + critic + finalizer）
└─ roleplay.py           (1140 行) 角色扮演 prompt 组装核心（被 story_forge 复用）

任务层  apps/api/app/tasks/story_tasks.py  章节任务化 + 连载 tick + drain
工具层  apps/api/app/mcp/server.py         read_bible / write_chapter / update_character_state /
                                           list_outline / check_story_consistency（MCP 创作工具）

数据层  story_projects / story_chapters / story_chapter_versions / story_characters / serial_schedules
```

### 2.3 生成流程（实测调用链）

**叙事模式（单章）**：

```
POST /story/chapters/{id}/generate
  └─ story_forge.generate_chapter
       ├─ roleplay._load_cards            # 角色卡（PNG/DB）
       ├─ _placeholder_cards              # 无卡时用 story_characters 文本
       ├─ _build_chapter_prompt           # ★ Prompt 组装（见 §3.3）
       ├─ resolve_text_provider           # ★ 单模型路由
       ├─ provider.generate               # ★ 单次 LLM 调用（tool_loop 默认关）
       ├─ _apply_regex                    # 正则后处理
       ├─ _snapshot_chapter               # 版本快照
       └─ chapter.status = "done"         # ★ 直接定稿，无门禁
```

**剧本模式**：场景 → 群聊引擎轮流发言（rounds 次 LLM 调用）→ 拼对话流 → 落库。

**AI 导演工作室**：

```
POST /creation/plan   主题 → 角色方案（1 次 LLM，JSON）
POST /creation/script 主题+选角 → 分幕大纲（1 次 LLM，JSON；variants 可并行 3 版）
POST /creation/review 大纲 → 制片人评审（1 次 LLM，0-10 分+弱点建议；★ 无修复循环）
POST /creation/setup  建角色卡 + 建群 + 角色入群
群内 @AI 导演 → director_assistant.director_chat_reply（开演/推进/总结）
POST /creation/publish 群演出 → 剧本 → story 项目首章
```

**Story Crew（已存在但手工串行）**：

```
POST /story/projects/{id}/crew  stage=director|writer|editor|stagehand|consistency
  director    → settings["direction"]      （下一章剧情方向）
  writer      → generate_chapter（复用）   （生成章节）
  editor      → chapter.notes["review"]    （审校报告 ★只存不改）
  stagehand   → story_characters.current_state（★字符串覆盖）
  consistency → settings["consistency_report"]（全书一致性 ★只存不改）
```

---

## 3. 当前 Prompt 架构（实测摘录）

### 3.1 角色卡字段（RoleplayCharacter / 角色卡 PNG）

`description`（外观背景）/ `personality`（性格）/ `scenario`（初始场景）/ `first_mes`（开场白）/ `system_prompt` / `post_history_instructions` / `depth_prompt`。

**没有任何结构化的人物价值 / 信念 / 世界观 / 关系 / 决策规则字段**。`depth_prompt`（SillyTavern V2）通常只承载叙述偏好（风格层）。

### 3.2 章节生成 system prompt 结构（`_build_chapter_prompt`）

```
【创作任务】你是小说《X》的执笔作者（genre）
【全书承诺】compass.intent（不可违反）
【当前阶段目标】compass.focus
【写作特征池】writing_style（已确认写法特征）
【故事梗概】synopsis
【世界观（世界书·前置）】lore before
【角色设定】bible（description/goals/arc/current_state + 技能）
【前情摘要】settings.summary
【前章回放】前 4 章 outline（已发生事实）
【世界观（世界书·后置）】lore after
【本次写作指令】instruction（如有）
【写作要求】第三人称/自然流畅/800-1500 字/严禁重复/每章新事件推进
```

user prompt = 已写章节正文（预算 4000 token）+ 本章大纲 + 指令 + 知识库检索片段。

### 3.3 Prompt 依赖的软约束形容词（问题 O 的证据）

- 「人物言行与性格一致」——无性格度量，模型自由解释
- 「场景/动作/对话自然流畅」——无法验证
- 「有完整的起承转合」——无结构验证
- 「严禁重复」——无相似度检测
- 「结尾禁止总结套话」——无检测
- director/editor/stagehand/consistency 同理，全部是"角色扮演式"软约束

---

## 4. 当前 Agent / Harness 架构（实测）

| 维度 | 现状 | 与目标架构差距 |
|---|---|---|
| Agent 数量 | 5 个手工触发阶段（crew）+ 圆桌角色 + 导演助理 | 无 Intent/Semantic Explorer/Value Architect/Causal Planner/Critic 门禁/Repair Agent/Final Editor 分工 |
| Agent 独立性 | **同一模型、同一 provider、不同 prompt 角色** | 生成与评价混用同一推理能力；无独立 Critic |
| Agent 协同 | 前端逐阶段手动触发，结果落库 | 无自动流水线、无状态总线、无 READ/PROPOSE/ACCEPT 协议 |
| 工具循环 | `_chapter_tool_loop`（MCP 工具，默认关闭）+ MCP 创作工具 | 工具存在但无状态校验；`update_character_state` 无 schema 校验 |
| 状态写入 | 各 Agent 直接 `update_*` 落库 | 无 State Validator 拦截；Style 层理论上可改任何字段 |

---

## 5. 当前质量控制（实测结论）

| 机制 | 存在？ | 性质 |
|---|---|---|
| 创作罗盘 compass（全书承诺+阶段目标） | ✅ | 好的 Prompt 层约束，但无法验证"守住没有" |
| 写作特征池 writing_style | ✅ | **文笔层**（风格延续），与故事成立性无关 |
| editor 审校 | ⚠️ | 报告存 notes，**不门禁、不修复** |
| consistency 全书审查 | ⚠️ | 报告存 settings，**不门禁、不修复** |
| review_project 制片人评审 | ⚠️ | 0-10 分 + 建议，**无修复循环** |
| roundtable critic/finalizer | ⚠️ | 单轮产物玩法，非长故事门禁 |
| CVI / CAI / CCI / WCI | ❌ | 不存在 |
| L0-L3 分层质量门 | ❌ | 不存在 |
| Diagnostic Report | ❌ | 不存在 |
| Repair Agent | ❌ | 不存在 |
| 情绪捷径 / 主题入侵 / 人物降维检测 | ❌ | 不存在 |
| 反事实人物测试 | ❌ | 不存在 |

---

## 6. 当前状态管理（实测结论）

| 状态 | 载体 | 问题 |
|---|---|---|
| 故事事实 | 章节正文字符串 + 前章回放 outline 截断 | 无结构化 world_state；事实只存在于文本 |
| 角色状态 | `story_characters.current_state` 字符串 | 无状态机、无迁移约束、无阶段语义（S0-S4） |
| 时间线 | 无 | outline 里隐含，无验证 |
| 因果关系 | 无 | 前章回放是"发生了什么"列表，非"为什么发生" |
| 未回收伏笔 | 无 | consistency 审查时人工读全文找 |
| 全书承诺 | settings.compass | 无"是否违反"的检测器 |
| 知识状态（角色知道什么） | 无 | 无法支撑信息不对称叙事 |
| 风格 | settings.writing_style | ✅ 唯一有结构的状态 |

---

## 7. 当前数据模型（实测）

```python
StoryProject:  id / user_id / title / synopsis / genre / status
                / character_asset_ids(JSON) / settings(JSON 垃圾桶) / created_at / updated_at

StoryChapter:  id / project_id / user_id / chapter_no / title / outline / content
                / status / word_count / model / task_id / notes(JSON) / timestamps

StoryChapterVersion:  chapter_id / content / word_count / note / timestamps

StoryCharacter: id / project_id / user_id / character_asset_id / name / role
                / description / goals / arc / current_state / skill_ids(JSON) / notes(JSON)

SerialSchedule: project_id / interval / next_run_at / batch_size / mode / fail_count ...
```

**技术债**：`settings` 一个 JSON 字段同时承载 compass / writing_style / summary / direction / knowledge_doc_ids / consistency_report 等 6+ 种异构语义——无 schema、无迁移、无版本。

---

## 8. 测试现状（实测）

| 测试文件 | 覆盖 | 缺失 |
|---|---|---|
| `tests/test_story_forge.py`（562 行） | CRUD / prompt 组装 / 生成成功路径 / 工具循环 / 连载 tick | **零创作质量断言** |
| `tests/test_story_api.py` | API 端点 | 端点行为，无质量 |
| `tests/test_story_versions.py` | 版本快照/还原 | 同上 |
| `tests/test_story_search_api.py` | 章节搜索 | 同上 |
| `tests/test_creation.py` | 选角/建群流程 | 同上 |
| `tests/test_roleplay.py` | 角色扮演 | 同上 |

**结论**：测试验证的是"管道通不通"，不是"写得好不好"。这与需求二十二（创作单元测试）差距为零。

---

## 9. 缺陷清单（按严重度）

### 🔴 CRITICAL（架构级，必须重构）

1. **D1 · 单次生成直通定稿**：`generate_chapter` 一次 LLM 调用即 `status=done`。任何 L0 质量问题都无法被拦截。
2. **D2 · 无人物决策模型**：人物 = 4 个字符串字段。系统不知道人物"最重要的东西是什么"（value hierarchy），无法判断行为是否成立。
3. **D3 · 无动机追踪**：无法回答"为什么是这个人/为什么是现在/换个人是否成立"。行为与价值之间没有可验证的链。
4. **D4 · 无故事状态**：长故事只存在于字符串与 outline 列表里。场景之间没有状态迁移，因果靠模型自觉。
5. **D5 · 评价与生成同源**：唯一审查者 editor 与 writer 同一模型同一 provider。没有独立视角，"自我审查"必然失效。
6. **D6 · 无质量门**：L0 门槛不存在，文笔可以无限掩盖逻辑崩坏——这正违反了 `Integrity > Style` 的最高原则。

### 🟠 MAJOR（架构相关，需改造）

7. **D7 · 主题第一联想垄断**：creation 选角 prompt 直接把 theme 给模型；"烟雨朦胧→江南油纸伞"式联想无 Semantic Diversity 拦截。
8. **D8 · 情绪捷径无检测**：亡妻/雨/旧照片/等待十年等套路无检测器，直接作为"深刻"被接受。
9. **D9 · 主题强迫人物**：compass 的 focus 是"本阶段最高优先级"直接压给 writer，无 Theme Intrusion 检测（人物是否被主题驱动）。
10. **D10 · 修复断链**：editor/consistency/review 三处审查全部"只报不改"，无 Repair Agent、无局部修复、无再验证。
11. **D11 · 状态写入无校验**：任何服务/MCP 工具可直接改 current_state/settings，无 State Validator。
12. **D12 · 模型路由单一**：所有 Agent 共享一个模型；无"生成用强模型、批判用独立模型"的路由。

### 🟡 MINOR（Prompt/工程层）

13. **D13 · 形容词约束**：「自然流畅」「性格一致」等不可验证约束充斥 prompt。
14. **D14 · settings JSON 垃圾桶**：6+ 种语义挤在一个字段，无 schema。
15. **D15 · 角色卡缺价值字段**：SillyTavern 卡结构没有价值层级承载位，需扩展 story_characters 而非角色卡。
16. **D16 · 时间线无验证**：consistency 靠 LLM 读全文找矛盾，无结构化时间线可查。
17. **D17 · 大纲即事实**：outline 同时是"计划"和"已发生摘要"，回放用 outline 冒充事实（可能含未发生内容）。

---

## 10. 风险点

| 风险 | 说明 | 等级 |
|---|---|---|
| 连载自动生成放大缺陷 | `serial_tick` 每 10 分钟自动产章，L0 缺陷被成倍复制 | 🔴 |
| 单模型幻觉自我印证 | writer 编造设定 → editor 与 writer 同模型 → 审查者认可幻觉设定 | 🔴 |
| 生成成本失控 | 多 Agent + 修复循环若不加预算，单章成本翻 5-10 倍 | 🟠 |
| 上游会话失效 | grok2api 账号限流（已知问题 12），长流程中途断链 | 🟠 |
| 风格层污染故事层 | writing_style 提取的是"写法"，但无防火墙保证不会反向改人物 | 🟠 |

---

## 11. 技术债清单

1. `settings` 字段无 schema（6+ 语义混装）
2. 角色卡字段与 story_characters 无价值模型承载位
3. `_build_chapter_prompt` 单函数 120 行，耦合 6 种上下文来源
4. `story_crew.run_crew` 巨型 if 分支（5 阶段一个函数）
5. 无 Prompt 版本管理（改 prompt 无法回滚/对比）
6. 无生成预算记账（每章 LLM 调用次数/成本不可见）
7. 无质量历史（"这章修过 3 次"无处可查）

---

## 12. 推荐改造方案（概要，详见 02/10）

| 优先级 | 改造 | 对应文档 |
|---|---|---|
| P0 | 建 Creative State Bus + StoryState/CharacterState 结构化 | 05 |
| P0 | 建 Character Constitution（含 Value Hierarchy） | 03/04 |
| P0 | 建 L0 Quality Gate（CVI/CAI/CCI/WCI）+ Diagnostic Report | 06 |
| P1 | Writer 与 Critic 解耦（独立角色/独立模型路由） | 07 |
| P1 | Repair Pipeline（诊断→局部修复→再验证，N 次上限） | 08 |
| P1 | 反事实测试 + 情绪捷径检测 + Theme Guard + 语义多样性 | 07 |
| P2 | 回归基准（50 Golden Cases + 14 个创作单元测试） | 09 |
| P2 | 存量链路无损接入（crew/creation/roundtable 复用新内核） | 10 |

---

## 13. 一句话审计结论

> 当前系统缺的不是"更好的 prompt"，而是**把创作当工程做**的那一整层：
> **结构化状态（State）＋ 独立批判（Critic）＋ 硬性质量门（Gate）＋ 机器可读诊断（Diagnostic）＋ 局部修复（Repair）＋ 回归基准（Benchmark）**。
> 这六样全部缺失或只有雏形——这是架构问题，不是 Prompt 问题。
