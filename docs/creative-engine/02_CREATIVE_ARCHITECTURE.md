# 02 · 创作智能架构（CREATIVE ARCHITECTURE）

> 目标架构设计：从「主题 → 直接生成」升级为「理解 → 建模 → 规划 → 生成 → 验证 → 诊断 → 修复 → 再验证 → 输出」。

---

## 1. 最高原则：Creative Integrity First

```
Integrity > Character > Causality > Narrative > Meaning > Creativity > Style
```

**禁止**（系统性，非建议）：

```
Style > Story ｜ Emotion > Character ｜ Theme > Character ｜ Plot > Character
Symbol > Meaning ｜ Beautiful Sentence > Causal Logic
```

**推导出的三条硬规则**：

1. **成立先于漂亮**：L0 门（人物/因果/世界/价值成立性）不过，禁止进入润色；润色不得反向修改 L0 层。
2. **人物先于剧情**：剧情事件必须能追溯为人物在价值结构下的选择产物；「为了让故事感人而让人物行动」直接 FAIL。
3. **主题是涌现的，不是注入的**：主题通过人物选择产生；「为了表现 X 而让人物做 Y」触发 THEME_FORCED_ACTION。

---

## 2. 架构总览：双层流水线 + 状态总线

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CREATIVE STATE BUS（创作状态总线）                   │
│   READ / PROPOSE / VALIDATE / ACCEPT —— 所有 Agent 不得直接写故事           │
│   ├─ StoryState（world/timeline/causal_graph/open_loops/...）             │
│   ├─ CharacterState（每人：constitution + 状态机 + 价值层级 + 动机链）      │
│   └─ FactTier（IMMUTABLE / IMPORTANT / FLEXIBLE 分级）                    │
└─────────────────────────────────────────────────────────────────────────┘
                                   ▲│ READ / PROPOSE
                                   │▼ ACCEPT（State Validator 裁决）
┌─────────────────────────────────────────────────────────────────────────┐
│                     CREATIVE PIPELINE（创作流水线）                        │
│                                                                          │
│   【理解层】 Intent Agent → Semantic Explorer → Theme Guard 预检            │
│   【建模层】 Character Architect → Value Architect → World Architect      │
│   【规划层】 Narrative Planner → Causal Planner → Scene Plan（含 gate 预判）│
│   【生成层】 Scene Writer（产出 Scene 草稿 + 显式状态变更提案）              │
│   【验证层】 Character Critic → Causal Critic → Theme Critic              │
│             → Diversity Critic（L0 门）                                    │
│   【修复层】 Diagnostic → Repair Agent（局部修复，只动被诊断处）→ 再验证      │
│   【输出层】 Style Agent（仅 FLEXIBLE 层）→ Final Editor（L0 全过后）        │
│                                                                          │
│   每层产物 = 结构化数据（JSON Schema），不是文本；每层可观测（log/审计）      │
└─────────────────────────────────────────────────────────────────────────┘
```

### 关键机制

1. **Scene → State Transition**（替代 Prompt → Scene）：
   每章产出「正文 + StateDelta」：新增事实 / 状态迁移 / 因果边 / 闭环伏笔 / 新开伏笔。
2. **Propose/Validate**：Writer 提交的是**提案**（正文 + StateDelta 声明），State Validator 校验 Delta 与正文一致才接受。
3. **L0 门是二元门**：CVI/CAI/CCI/WCI 任一低于阈值 → REJECT，进 Repair；禁止加权平均掩盖。
4. **Repair 有预算**：单场景 Repair 上限 N 次（默认 2）；超限 → HUMAN_REVIEW_REQUIRED，不无限重生成。
5. **Style Firewall**：Style Agent 只见 FLEXIBLE 层文本，改动只落 `story_chapter_versions` 的 style 变体，永不触碰 State。

---

## 3. 分层定义（每层 = 数据结构 + Agent + 验证）

| 层 | 产出物 | 主要 Agent | 门 |
|---|---|---|---|
| L0 Integrity | 人物/价值/因果/世界成立性 | Character Critic / Causal Critic / Theme Critic | **硬门**：CVI≥0.85 CAI≥0.85 CCI≥0.85 WCI≥0.90 |
| L1 Narrative | 冲突/弧线/节奏/意义/情绪真实 | Narrative Critic | 软门：报告 + 建议 |
| L2 Creativity | 新颖/语义多样/叙事多样/具体/意外 | Diversity Critic | 软门：报告 + 建议 |
| L3 Expression | 语言/风格/意象/对白/节奏 | Style Critic | 软门：报告 + 建议（L0 通过后才执行） |

**门顺序**：L0 是硬门槛，L1/L2 是质量杠杆，L3 是最后的润色层。**禁止跳层**。

---

## 4. 数据流（一次完整生成）

```
主题输入
  │
  ▼
① Intent Agent        → 澄清意图：主题的语义边界、用户真实目标、禁止联想清单
  ▼
② Semantic Explorer   → Semantic Expansion：≥3 个语义方向（自然/工业/工程/医学/法律/...）
                         Semantic Diversity Score ≥ 阈值才放行（防第一联想垄断）
  ▼
③ Character Architect → Character Constitution（每人 22 字段，见 03）
  ▼
④ Value Architect     → Value Hierarchy（数值化价值层级）+ 情绪触发器（与核心价值分离）
  ▼
⑤ World Architect     → 世界规则（IMMUTABLE）+ 时间线骨架 + 地点/机构/知识状态
  ▼
⑥ Narrative Planner   → 全书弧线 + 章节点（含每章目标与悬念管理）
  ▼
⑦ Causal Planner      → 因果图草案：事件链 A→B→C→D，标注角色/环境必然性来源
  ▼
⑧ Scene Writer        → 写场景草稿 + StateDelta 提案（只写，不评价自己）
  ▼
⑨ Critic 门（并行/串行）→ Character/Causal/Theme/Diversity 四 Critic 独立审查
       │
       ├─ PASS → ⑪ Style Agent（仅 FLEXIBLE 层）→ Final Editor → 输出
       │
       └─ FAIL → ⑩ Diagnostic → Diagnostic Report（机器可读）→ Repair Agent
                 → 局部修复 → 再验证（⑨）→ 最多 N 轮 → 超限 HUMAN_REVIEW_REQUIRED
```

---

## 5. 状态模型总纲（详见 05）

| 状态 | 结构 | 关键约束 |
|---|---|---|
| `StoryState` | world_state / timeline / character_states / relationship_states / value_states / goal_states / open_loops / resolved_loops / causal_graph / knowledge_state / location_state / symbol_state / theme_state | 每场景一次 State Transition |
| `CharacterState` | 状态机阶段 S0-S4 + 当前价值权重 + 当前目标 + 当前知识 + 情绪状态（独立于价值） | 状态迁移必须由事件触发，禁止无过程顿悟 |
| `FactTier` | IMMUTABLE / IMPORTANT / FLEXIBLE | 低层 Agent 禁止改高层事实 |

---

## 6. 可观测性 / 可回滚 / 可测试设计

- **可观测**：每场景生成产出 `Creative Quality Report`（CVI/CAI/CCI/WCI + Critical/Major/Minor + Repair History + Final Status）；所有 Agent 调用入 `ai_call_log`（已有表）+ 新增 `creative_run` 审计表（详见 10）。
- **可回滚**：Prompt 版本化（`creative_prompts` 表）；State 快照随章节版本（复用 `story_chapter_versions` + 新增 state 快照列）。
- **可测试**：全部质量检查器（CVI 检查项、反事实测试、情绪捷径、主题入侵）实现为**确定性函数 + LLM 混合**——确定性部分（正则/规则/计数）单元可测，LLM 部分由 Golden Case 回归锁行为（详见 09）。

---

## 7. 与现有系统的兼容策略（增量改造，不推翻）

| 现有资产 | 处置 |
|---|---|
| `story_forge` CRUD / 导出 / 连载 | **保留不动**，作为存储与执行底座 |
| `_build_chapter_prompt` | 重构为 `Context Assembler`（从 State 组装，而非自由拼接） |
| `story_crew`（director/editor/stagehand/consistency） | **升级复用**：editor→Character/Causal Critic 入口；stagehand→State Validator 的提案来源；consistency→CCI 全书级检查 |
| `creation_service`（AI 导演工作室） | 选角阶段插入 Value Architect；剧本阶段插入 Causal Planner |
| `roundtable_service` | 保留玩法；最终定稿前过 L0 门 |
| `roleplay` 群聊引擎 | 保留；剧本模式生成的章节同样走 State 抽取 + L0 门 |
| MCP 创作工具 | `write_chapter`/`update_character_state` 改为**提案模式**（经 State Validator） |
| 连载 `serial_tick` | 接入流水线：自动生成也走 L0 门，失败进 HUMAN_REVIEW_REQUIRED 而非静默落库 |

---

## 8. 成本与预算控制

- **生成预算**：单场景默认 LLM 调用预算 = 1（writer）+ 4（critics，可并行）+ 2（repair 上限 × 重验证）+ 1（style）≈ 8-12 次调用上限；超预算强制 HUMAN_REVIEW_REQUIRED。
- **Critic 聚合**：四个 Critic 可并行（同一章），串行仅当存在依赖（如 CCI 依赖 CVI 结论）。
- **模型路由**（见 07 §9）：writer 用主模型；critic 可用独立/更强模型或同模型独立温度；确定性检查器（正则/计数）零成本先跑，过滤明显问题再上 LLM。

---

## 9. 本架构与需求三十（验收标准）的对应

| 验收项 | 架构落点 |
|---|---|
| 1 不按第一联想生成 | ② Semantic Explorer + ⑥/⑦ 规划 |
| 2 建立价值层级 | ④ Value Architect + 03/04 |
| 3 解释动机链 | ④ Motivation Trace 落库 + ⑨ 验证 |
| 4 识别价值降维 | ⑨ CVI·Value Preservation / Emotional Override |
| 5 识别情绪捷径 | ⑨ Emotional Shortcut Detector（07 §5） |
| 6 识别主题强迫 | ⑨ Theme Guard（07 §4） |
| 7 反事实人物测试 | ⑨ Counterfactual Test（07 §6） |
| 8 检测因果断裂 | ⑨ CCI（07 §3） |
| 9/10 维护 Story/Character State | ⑤ 状态总线 + 每场景 State Transition |
| 11 生成中质量检查 | ⑨ Critic 门（生成管线内，非事后） |
| 12/13/14 诊断/局部修复/再验证 | ⑩ Repair Pipeline（08） |
| 15 L0 不被文笔掩盖 | L0 二元门 + 禁止加权平均 |
| 16 过 L0 才润色 | Style Firewall 顺序 |
| 17/18 回归基准与指标测试 | 09（50 Golden Cases + 14 个创作单元测试） |
