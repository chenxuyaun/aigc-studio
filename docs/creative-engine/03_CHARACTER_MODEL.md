# 03 · 人物模型（CHARACTER MODEL）

> Character Constitution —— 从「姓名+年龄+职业+性格」升级为「人物决策模型」。
> 人物不是标签集合，而是一套可推导行为的约束系统。

---

## 1. 设计原则

1. **人物 = 约束系统，不是描述文本**：行为必须能从模型推导，模型必须能拒绝不兼容行为。
2. **人物 ≠ 情绪触发器**：核心价值与情绪触发器分离（§4）。
3. **人物有层级**：最高层价值（value_hierarchy 顶端）决定重大行为；低层情绪只能解释即时反应，不能解释重大选择。
4. **人物有过程**：状态迁移必须由事件驱动，禁止无过程顿悟（State Machine §6）。
5. **人物关系参与模型**：替换关系对象（妻子→父亲→战友）必须改变故事，否则关系没进入模型（反事实 Test E）。

---

## 2. Character Constitution（22 字段 Schema）

```yaml
character:
  identity:            # 身份：姓名/年龄/职业/社会角色（可含复数身份）
  worldview:           # 世界观：认为世界如何运作（如：世界由规则与责任维系）
  beliefs:             # 信念集：[]（如：工程质量即生命）
  core_values:         # 核心价值观：[]（3-6 条，如 责任/工程伦理/公共安全/人民利益）
  value_hierarchy:     # 价值层级：{value: weight 0-1}（顶部=最高优先，见 04）
  mission:             # 使命：一生要达成的事（如：守住这座桥，直到它退休）
  goals:               # 当前目标：[]（按优先级，随故事变化）
  desires:             # 欲望：[]（可能违反价值，是冲突源）
  fears:               # 恐惧：[]（深度恐惧，非表面害怕）
  needs:               # 深层需求：[]（Maslow 级，如 被需要/意义感/安全感）
  relationships:       # 关系：[{name, relation, emotional_weight, value_link}]
                       #   value_link：这段关系挂在哪条价值上（关键！）
  history:             # 重大经历：[]（时间线锚点，IMMUTABLE）
  skills:              # 技能：[]（含专业能力：如 桥梁病害检测/施工管理）
  weaknesses:          # 弱点：[]（人格缺陷，非技能短板）
  contradictions:      # 矛盾：[]（内在张力，人物深度的来源）
  boundaries:          # 边界：能做什么/不能做什么的底线
  moral_limits:        # 道德上限：[]（如：绝不牺牲他人安全）
  decision_rules:      # 决策规则：[]（if-then 式，从价值层级推导）
  emotional_triggers:  # 情绪触发器：[]（⚠️ 与核心价值分离，见 §4）
  character_arc:       # 弧线：起点→中点→终点（价值变化轨迹，可空=无成长）
  state:               # 状态机当前阶段：S0-S4 + 状态详情（见 §6）
```

### 关键约束

- `core_values` 与 `value_hierarchy` 必须一致：core_values 是层级顶端的子集。
- `mission` 必须挂在 `value_hierarchy` 的某条价值上（Mission ← Value）。
- `relationships[].value_link` 必填：关系不挂价值的关系不进入模型（反事实 Test E 的根源）。
- `emotional_triggers` 与 `value_hierarchy` **禁止自动互相推导**：妻子可以是最强情绪触发器，但未必是最高价值。

---

## 3. 与现有数据的映射（迁移策略）

现有 `story_characters` 只有 4 个文本字段，升级为：

```
story_characters（保留现有列，向后兼容）
├─ description      → 保留（外观/背景摘要）
├─ goals            → 保留（迁移到 constitution.goals 的简写）
├─ arc              → 保留（迁移到 character_arc 的简写）
├─ current_state    → 保留（= constitution.state 的文本投影，双写）
└─ NEW: constitution JSON（完整 22 字段）
     └─ NEW: constitution_version（模型/时间，Prompt 版本化配套）
```

角色卡（RoleplayCharacter/PNG）**不改结构**：Constitution 是"角色在具体故事中的实例"（story_characters），不是角色卡本身——同一角色卡可在不同项目拥有不同 Constitution（这正是故事创作与角色陪伴的本质区别）。

---

## 4. 核心价值 vs 情绪触发器（关键区分）

| 维度 | 核心价值 | 情绪触发器 |
|---|---|---|
| 作用 | 决定**重大选择**（是否剪彩/是否辞职/是否救人） | 决定**即时反应**（颤抖/沉默/落泪/发怒） |
| 来源 | worldview → mission 的推导 | 历史创伤/关系记忆 |
| 变化 | 缓慢（弧线终点才可能变） | 快速（随情境） |
| 示例 | 工程伦理 0.93 / 责任 0.95 | 提到"那座垮掉的桥"→ 情绪波动 |

**规则**：
- 情绪触发器**不得**成为重大行为的唯一理由（触发 `EMOTIONAL_OVERRIDE` 检查）。
- 情绪触发器可以**放大/延迟**价值驱动的行为，但方向必须与价值一致；方向相反时必须有价值层冲突剧情支撑。

---

## 5. 决策模型（Decision Model）

重大行为必须可推导为：

```
Situation（情境）
   + Character Constitution（价值层级 + 决策规则 + 边界）
   + Knowledge State（人物知道什么）
   ────────────────────────────────
   → Decision（决策）
   → Action（行动）
   → Consequence（后果，更新 State）
```

**决策规则的生成**：由 Value Architect 从 value_hierarchy 机械推导（确定性规则），示例：

```yaml
character: 守桥人 陈工
value_hierarchy:
  public_duty: 1.00        # 人民利益最高
  responsibility: 0.95     # 岗位责任
  professional_ethics: 0.93
  family: 0.75
  personal_emotion: 0.65
  reputation: 0.30

decision_rules（推导示例）:
  - if 公共安全受到威胁 and 有可采取的措施:
      action = 采取措施，即使牺牲个人利益（public_duty=1.00 最高）
  - if 个人情感诉求 and 职业职责冲突:
      需评估冲突价值权重差（0.93 vs 0.65）；差 < 0.2 时人物产生犹豫（内心冲突场景），
      差 ≥ 0.2 时按高权重行动但承受内心代价（可写为内在冲突，不得直接反转）
  - if 行为会伤害他人安全: 禁止（moral_limits）
```

---

## 6. Character State Machine（S0-S4）

```
S0 稳态（既有价值秩序）
 │  事件（Event：外部冲击/信息揭示/关系变化）
 ▼
S1 认知变化（人物接收/拒绝新信息；可停滞→回到 S0 或固守）
 │  冲突（价值被考验：价值 vs 欲望/恐惧/他者价值）
 ▼
S2 价值冲突（可写内心戏；此阶段是"深刻"的正确载体，不是形容词）
 │  选择（Decision：按 decision_rules + 情境压力）
 ▼
S3 行为（Action：可观察，落库进 StateDelta）
 │  后果（Consequence：世界/关系/自我认知变化）
 ▼
S4 成长或固守（价值权重变化/弧线推进；不成长也是结果，但要交代理由）
```

**禁止**：
- S0 → 直接 S4（无过程顿悟）→ 触发 `UNMOTIVATED_EPIPHANY` 检测。
- S2 → S3 用「剧情需要」跳过决策（人物必须经历选择，哪怕选择是"不选"）。
- 人格突变：S4 只允许调整 value_hierarchy 权重（缓慢），不允许翻转 core_values（除非弧线明确设计为"信仰崩塌"，且必须多场景铺垫）。

---

## 7. Character State 的落库结构

```json
{
  "stage": "S2",
  "stage_since": "ch5",
  "value_weights": {"public_duty": 1.0, "family": 0.7},
  "active_conflict": "剪彩 vs 检查报告",
  "pending_decision": null,
  "knowledge": ["知道 3 号墩存在隐患"],
  "relationship_deltas": [{"with": "妻子", "delta": "疏远-1"}],
  "emotion": {"primary": "焦虑", "intensity": 0.6}
}
```

每章由 Scene Writer 的 StateDelta 提案更新；Stagehand（剧务）从"自由写状态文本"升级为"按状态机阶段推进"。

---

## 8. 反事实测试接口（供 Critic 调用）

```python
counterfactual(character, action, variant) -> bool
# variant:
#   drop_emotion_object  删核心情感对象（妻子→不存在），行为是否仍成立？
#   drop_theme           删主题，行为是否仍成立？
#   change_profession    换职业（守桥人→教师），行为是否改变？
#   change_value_hierarchy 价值层级互换（family↔public_duty），行为是否改变？
#   substitute_relation  妻子→父亲/战友/老师，故事是否完全不变？
```

- Test A/E 通过但行为解释里没有价值参与 → `MOTIVATION_DOWNGRADE`（人物被降维成情感符号）。
- Test C/D 行为不变 → 人物职业/价值没有真正参与模型 → `GENERIC_CHARACTER`（可替换木偶）。

---

## 9. 与角色陪伴系统的关系（不越界）

- 角色陪伴（roleplay）的 persona/记忆系统负责**日常对话一致性**；
- 故事创作（story）的 Constitution 负责**重大行为可推导性**；
- 二者共用角色卡作为素材，但 Constitution 只在 story_characters（故事实例）层建立，**不污染**角色卡的通用人格。
