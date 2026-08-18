# 04 · 价值模型（VALUE MODEL）

> Value Hierarchy + Motivation Trace + CVI（Character Value Integrity，L0 一级质量指标）。
> 本模块是整个升级中最重要的部分：它决定系统能否区分"人物核心价值"与"人物情绪触发器"。

---

## 1. Value Hierarchy（价值层级）

### 1.1 定义

`value_hierarchy` 是人物价值权重的数值化排序：**人物最重要的东西是什么**。

```yaml
value_hierarchy:
  public_duty: 1.00          # 人民利益/公共安全（最高）
  responsibility: 0.95       # 岗位责任
  professional_ethics: 0.93  # 工程伦理
  family: 0.75               # 家庭
  personal_emotion: 0.65     # 个人情感
  reputation: 0.30           # 名誉
```

### 1.2 硬规则

1. **禁止自动提升**：「妻子」「孩子」「爱情」「死亡」「遗物」**不得**被自动提升为最高层动机。
2. **必须区分**：核心价值（决定重大行为）与情绪触发器（决定即时反应）是两套独立数据。
3. **权重差语义**：
   - 差 ≥ 0.2：按高权重行动，低权重方承受代价（可写内在冲突，但**不得反转**）。
   - 差 < 0.2：人物产生真实犹豫 → 这是"两难"剧情的**唯一合法来源**（否则是假两难）。
4. **变化约束**：单章内权重漂移 ≤ 0.05；弧线终点可大改但必须多场景铺垫（S4 阶段）。

### 1.3 价值层级 vs 主题

- 主题 = 全书层面的价值命题（涌现自多个角色的价值冲突）；
- 价值层级 = 单个角色的内部排序。
- **主题不得修改价值层级**（Theme Guard 管这个）；价值层级变化只能来自人物自身的经历（弧线）。

---

## 2. Motivation Trace（动机链）

### 2.1 定义

每一个**重大人物行为**都必须可追溯为一条完整链条：

```
Worldview（世界观）
   ↓ 推导
Value（价值，具体到 value_hierarchy 中的一条）
   ↓ 激活
Mission（使命）
   ↓ 具体化
Goal（当前目标）
   ↓ 遭遇
Situation（情境，外部世界状态）
   ↓ 产生
Conflict（冲突：价值 vs 欲望/恐惧/他者价值）
   ↓ 裁决
Decision（决策：按 decision_rules + 情境压力）
   ↓ 执行
Action（行动：可观察行为）
   ↓ 反馈
Consequence（后果：世界/关系/自我认知变化 → 更新 State）
```

### 2.2 落库结构（每章 StateDelta 的一部分）

```json
{
  "action_id": "act-003",
  "character": "陈工",
  "action": "通车日没有参加剪彩",
  "trace": {
    "worldview": "工程质量即生命",
    "value": "professional_ethics: 0.93",
    "mission": "守住这座桥",
    "goal": "完成 3 号墩隐患复检",
    "situation": "剪彩前夜收到复检报告异常",
    "conflict": "职业责任(0.93) vs 集体荣誉/个人露面(0.30)",
    "decision": "按 decision_rule#1：公共安全优先",
    "action": "缺席剪彩，在桥墩现场",
    "consequence": "报告公开；与妻子的隔阂加深（relationship_delta）"
  },
  "counterfactual_ok": {"drop_emotion_object": true, "change_profession": false}
}
```

### 2.3 强制追问（Critic 执行）

对每个重大行为，Critic 必须能回答：

| 问题 | 不通过时的诊断 |
|---|---|
| 为什么？ | `MISSING_MOTIVATION` |
| 为什么是这个人物？ | `SWAPPABLE_CHARACTER`（换成谁都成立） |
| 为什么是现在？ | `WRONG_TIMING`（时机无叙事必然性） |
| 为什么不能换成其他人？ | `SWAPPABLE_CHARACTER` |
| 如果没有妻子，行为是否仍成立？ | 不成立 → `MOTIVATION_DOWNGRADE`（情感依赖过重） |
| 如果换一个职业，行为是否仍成立？ | 不变 → `PROFESSION_NOT_INTEGRATED` |
| 行为主要由低层情绪驱动，而人物有更高价值？ | **`CHARACTER_VALUE_HIERARCHY_COLLAPSE`**（一级事故，见 §4） |

---

## 3. CVI —— Character Value Integrity（L0 一级指标）

### 3.1 定义

CVI 衡量：**人物的行为、决策、情感反应是否与其价值结构一致，且价值结构是否被尊重**。
CVI 不是文笔分，不是情绪分，不是主题表达分——它是**人物成立性**的度量。

```
CVI = f(Value Preservation, Value Conflict, Value Evolution,
        Motivation Alignment, Decision Consistency,
        Character Agency, Emotional Override, Theme Override)
```

### 3.2 八项检查（每项 0-1 分，CVI = 加权和）

| # | 检查 | 含义 | 检测目标 | 权重 |
|---|---|---|---|---|
| 1 | **Value Preservation** | 行为是否与 value_hierarchy 兼容 | 行为违反最高价值且无冲突剧情 → 0 分 | 0.20 |
| 2 | **Value Conflict** | 两难是否来自真实价值冲突（权重差 < 0.2） | 假两难（其实没冲突硬拗）→ 扣分 | 0.15 |
| 3 | **Value Evolution** | 价值变化是否有过程、有铺垫 | 顿悟式翻转 → 扣分 | 0.10 |
| 4 | **Motivation Alignment** | 重大行为是否有完整 Motivation Trace | 缺链/断裂 → 扣分 | 0.20 |
| 5 | **Decision Consistency** | 决策是否符合 decision_rules | 同情境不同决策且无解释 → 扣分 | 0.10 |
| 6 | **Character Agency** | 人物是自己推动故事，而非被剧情推动 | PLOT_FORCED_ACTION → 扣分 | 0.15 |
| 7 | **Emotional Override** | 情绪是否越权决定重大行为 | 情绪触发器替代价值 → 重扣 | 0.05 |
| 8 | **Theme Override** | 主题是否强迫人物行动 | THEME_FORCED_ACTION → 重扣 | 0.05 |

> 权重可调（config），但**禁止加权平均掩盖 L0**：任何单项触发 CRITICAL 失败类型（§4）时直接 FAIL，不论总分。

### 3.3 门限

```
CVI >= 0.85  → PASS（可进入 L1）
CVI <  0.85  → FAIL → 必须生成 Diagnostic Report（06）→ 进 Repair Pipeline（08）
```

**修复禁令**：CVI FAIL 时，**禁止**通过增加金句/形容词/意象/悲情/象征/情绪来修复。
必须返回人物/剧情设计阶段（Character Architect / Value Architect / Causal Planner）。

---

## 4. 失败类型字典（failure_type，机器可读）

| failure_type | 含义 | 严重度 | 修复回退阶段 |
|---|---|---|---|
| `CHARACTER_VALUE_HIERARCHY_COLLAPSE` | **价值层级崩塌**：低层情感动机取代高层价值成为行为主因（如"守桥人→沉溺亡妻的丈夫"） | CRITICAL | ④ Value Architect |
| `MOTIVATION_DOWNGRADE` | 动机降级：人物被降维成单一情感符号 | CRITICAL | ③ Character Architect |
| `EMOTIONAL_OVERRIDE` | 情绪越权决定重大行为 | HIGH | ④ + ⑧ Scene Writer |
| `THEME_FORCED_ACTION` | 主题强迫人物行动 | CRITICAL | ⑦ Narrative Planner |
| `PLOT_FORCED_ACTION` | 剧情强迫人物行动 | CRITICAL | ⑦ Causal Planner |
| `AUTHORIAL_FORCED_ACTION` | 作者解释式行动（"他之所以…是因为…"叙述腔） | HIGH | ⑧ Scene Writer |
| `COINCIDENCE_DEPENDENCY` | 重大转折依赖巧合 | HIGH | ⑦ Causal Planner |
| `MISSING_MOTIVATION` | 行为无动机链 | HIGH | ⑧ Scene Writer |
| `VALUE_FLIP_WITHOUT_PROCESS` | 价值无过程翻转 | HIGH | ④ Value Architect |
| `UNMOTIVATED_EPIPHANY` | 无过程顿悟 | MEDIUM | ⑧ Scene Writer |
| `GENERIC_CHARACTER` | 可替换木偶（职业/价值未参与模型） | MEDIUM | ③ Character Architect |

**示例判定（REG RESSION_CASE_001 桥的名字）**：

> 输入："通车那天他没去剪彩，因为想起亡妻。"
> 判定：`CHARACTER_VALUE_HIERARCHY_COLLAPSE`，severity=CRITICAL，CVI≈0.30。
> 依据：人物最高价值 public_duty/professional_ethics（1.00/0.93）在行为解释中完全缺席；
> 妻子（情绪触发器，family=0.75）被错误提升为行为主因。违反 Value Preservation + Emotional Override。
> 正确方向：妻子进入情感层/历史层/内在冲突层（如：剪彩日想起妻子生前说过"桥通了就一起走一趟"——
> 情绪触发器放大他此刻的复杂感受），但**行为主因仍是职业价值**（复检/责任）。

---

## 5. CAI —— Character Agency Integrity（L0 二级指标）

CAI 衡量：**人物是否自己推动故事**。

```
CAI = 1 - (PLOT_FORCED_ACTION 数 + THEME_FORCED_ACTION 数 + EMOTION_FORCED_ACTION 数
           + AUTHORIAL_FORCED_ACTION 数 + COINCIDENCE_DEPENDENCY 数) / 重大行为数
CAI >= 0.85 → PASS
```

**硬规则**：如果一个人物做某件重大事情的唯一原因是"这样故事会更感人"→ **直接 FAIL**（不记分，直接 FAIL，无加权）。

---

## 6. 与现有代码的对接点

| 现有位置 | 对接 |
|---|---|
| `story_characters` | 新增 `constitution`（含 value_hierarchy/decision_rules）JSON 列 |
| `story_crew.stagehand` | 从"自由写 current_state"升级为"按状态机 + 价值权重更新" |
| `story_crew.editor` | 升级为 CVI/CAI 检查入口（按 §3.2 八项出结构化报告） |
| `creation_service.plan_project` 选角 | 角色方案字段增加 value_hierarchy 生成（Value Architect 注入） |
| `_build_chapter_prompt` | bible 组装增加【价值层级】【决策规则】【动机约束】段 |
| MCP `update_character_state` | 增加 schema 校验（stage/value_weights/active_conflict） |
