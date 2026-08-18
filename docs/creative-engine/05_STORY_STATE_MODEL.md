# 05 · 故事状态模型（STORY STATE MODEL）

> 让长故事从"一个字符串"升级为"一棵可验证的状态树"。
> 核心转变：`Prompt → Scene` 变成 `Scene → State Transition`。

---

## 1. StoryState（完整 Schema）

```yaml
StoryState:
  version: int                     # 状态版本（每场景 +1，快照可回滚）
  project_id: str

  world_state:                     # 世界状态
    rules: []                      # 世界规则（IMMUTABLE）：如 物理/魔法/社会制度
    locations: []                  # 地点状态：{id, name, status, occupants}
    institutions: []               # 机构/组织状态（如 工程局、法院）
    facts: []                      # 已确立事实（谁在何时何地做了什么）

  timeline:                        # 时间线（IMMUTABLE 骨架 + 事件）
    anchors: []                    # 关键时间节点（桥建成日、事故日……）
    events: []                     # 事件序列：{at, chapter, event, caused_by}

  character_states: {}             # 每人一份（见 03 §7）
  relationship_states: []          # 关系状态：{a, b, trust, closeness, note}
  value_states: {}                 # 每人价值权重当前值（弧线追踪）

  goal_states: []                  # 目标状态：{owner, goal, status: active/done/failed/abandoned}
  knowledge_state: []              # 知识状态：{character, knows, since_chapter}
                                   #   关键：支撑信息不对称叙事（谁不知道什么）

  open_loops: []                   # 未回收伏笔/悬念：{id, planted_chapter, desc, expected_payoff}
  resolved_loops: []               # 已回收：{id, resolved_chapter, how}

  causal_graph:                    # 因果图
    nodes: []                      # {id, type: event/decision/state_change, desc, chapter}
    edges: []                      # {from, to, kind: causes/enables/forces, necessity: role|environment|chance}

  symbol_state: []                 # 意象/象征登记：{symbol, first_use, instances, meaning}
                                   #   防象征过载：同一意象反复出现且无意义演进 → 触发检测
  theme_state:                     # 主题状态
    propositions: []               # 主题命题：{claim, characters_voicing, chapter}
                                   #   主题 = 人物价值冲突的涌现，非注入
    emergence_score: float         # 主题涌现度（人物驱动 vs 主题注入）
```

### 1.1 更新协议（每章必须）

```
Scene Writer 产出:
  content: str                    # 正文
  state_delta: {                  # 状态变更提案
    facts_added, timeline_events, character_deltas,
    relationship_deltas, goal_updates, knowledge_updates,
    loops_opened, loops_resolved, causal_edges,
    symbol_updates, theme_evidence
  }

State Validator 校验:
  1. delta 中的每个声明都能在正文中找到证据（text-anchor）
  2. 不违反 IMMUTABLE 事实
  3. 因果边 from/to 都存在
  4. loop 关闭引用的是真实 open loop
  5. 字符状态迁移符合状态机（S0→S1 不可跳 S4）
  → ACCEPT（状态前进）或 REJECT（退回 writer 补证据/修声明）
```

---

## 2. 不可变事实分级（Fact Tiering）

```yaml
IMMUTABLE:   # 任何人（除全书级编辑）不得修改
  - 人物核心价值（value_hierarchy 结构）
  - 人物重大经历（history）
  - 世界核心规则（world_state.rules）
  - 时间线关键节点（timeline.anchors）
  - 核心关系（relationships 的存在性）

IMPORTANT:   # 修改需 State Validator 批准（防误改）
  - 职业细节 / 习惯 / 地点细节 / 次要事件
  - 人物非核心状态（当前目标、知识状态）

FLEXIBLE:    # Style/润色层可自由改
  - 措辞 / 修辞 / 场景细节 / 意象 / 叙述声音
```

**执行**：State Validator 维护 `fact_tier` 索引；任何 Agent 的 StateDelta 触碰高层事实 → REJECT。
Style Agent 的权限范围 = FLEXIBLE 层 + 章节文本层，**物理上无法触达** StoryState（接口分离）。

---

## 3. Creative State Bus（创作状态总线）

### 3.1 协议

```
所有 Agent 只有两个动作:
  READ STATE          → 按需读 StoryState 的任意子集（带订阅/快照）
  PROPOSE CHANGE      → 提交 {target, delta, justification, text_anchor}

State Validator（唯一写入口）:
  validate(delta) → ACCEPT | REJECT(reason) | NEEDS_CLARIFICATION
```

### 3.2 防止的问题（直接对应现有风险）

| 现状风险 | 总线解决 |
|---|---|
| Style Agent 突然改变人物 | Style 的 PROPOSE 只允许 FLEXIBLE 层 |
| Plot Agent 突然改变人物价值 | value_hierarchy 是 IMMUTABLE，PROPOSE 被 REJECT |
| Emotion Agent 修改人物背景 | history 是 IMMUTABLE |
| 各 Agent 直接 update 落库 | 唯一写入口 = State Validator |

### 3.3 实现形态（Python）

```python
class StateValidator:
    async def validate(self, project_id, delta) -> ValidationResult:
        # 1. tier 检查：delta 触碰的字段 ∈ 允许层级
        # 2. text-anchor 检查：每条变更在正文有锚点
        # 3. 状态机检查：character_deltas 符合迁移规则
        # 4. 因果检查：causal_edges 节点存在
        # 5. 幂等：同内容重复提案合并
        # ACCEPT → 应用 + 版本号 +1 + 审计日志
        # REJECT → 返回 reason + 建议修正方向
```

---

## 4. Scene → State Transition 全流程

```
                     ┌────────────────────────────────────────────┐
  章大纲（Narrative Planner 产出，含本场目标/悬念意图）             │
                     ▼                                            │
  Scene Writer 写正文 + state_delta 提案  ◄── READ：相关子集        │
                     │                                            │
                     ▼                                            │
  State Validator ── ACCEPT ──► StoryState v+N（落库 + 快照）      │
     │                │                                           │
     │ REJECT         ▼                                           │
     │         Critic 门（CVI/CAI/CCI）◄──────────────────────────┤
     │                │                                           │
     │                ├─ PASS → 下一章（Narrative Planner 用新状态规划）│
     │                └─ FAIL → Diagnostic → Repair（08）          │
     └──► 返回 writer 补充证据/修正 delta（小修，不重写正文）        │
                     └────────────────────────────────────────────┘
```

---

## 5. 与现有存储的兼容（增量，不推翻）

```
现有表                    新增/升级
─────────────────────────────────────────────────────────
story_projects.settings  → 迁移：story_states 表（project_id PK）
                            settings 保留为"前端展示用设置"，State 不再往里塞
story_characters         → 新增 constitution JSON 列（03 §3）
                            current_state 双写（文本投影，兼容现有前端）
story_chapters.notes     → 新增 state_delta JSON（每章的状态变更审计）
story_chapter_versions   → 版本快照扩展：同时快照 StoryState（可整体回滚）
story_chapters.outline   → 语义澄清：outline = 计划（生成前）；事实以 state_delta 为准
                            （修复 D17：大纲不再冒充"已发生事实"）
```

---

## 6. 状态快照与回滚

- 每章 ACCEPT 后：`story_states_snapshots`（project_id, chapter_no, state_json, created_at）追加一条。
- 回滚：还原章节正文 + 恢复对应章节的状态快照（与现有 `restore_chapter_version` 联动）。
- 审计：`creative_runs` 表（详见 10 §3）记录每次 PROPOSE/ACCEPT/REJECT + 调用 Agent + 成本。

---

## 7. 一致性检查的基座

现有的 `consistency`（全书一致性审查）从"读 6 万字找矛盾"升级为：

```
1. 确定性检查（零 LLM，直接查 State）:
   - 时间线冲突：timeline.events 排序自洽
   - 事实矛盾：facts 重复/矛盾检测
   - 知识泄漏：knowledge_state 里"不该知道的人知道了吗"
   - 伏笔遗忘：open_loops 超 N 章未回收 → 告警
2. LLM 检查（人类级语义）: 仅查 State 之外的内容（语气/细节一致性）
```

这使一致性检查从"事后找茬"变成"每章自动维护"。
