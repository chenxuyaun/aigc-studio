# 06 · 质量门（QUALITY GATE）

> L0 Integrity Gate 是硬门槛。禁止加权平均，禁止"文笔掩盖逻辑"。

---

## 1. 质量门分层总览

| 层 | 指标 | 门限 | 性质 |
|---|---|---|---|
| **L0 Integrity** | CVI ≥ 0.85 ｜ CAI ≥ 0.85 ｜ CCI ≥ 0.85 ｜ WCI ≥ 0.90 | **硬门** | 不通过 → REJECT / REVISE，禁止进润色 |
| L1 Narrative | Conflict / Arc / Pacing / Meaning / Emotional Authenticity | 软门 | 报告 + 建议，不阻断（可带 MUST 项） |
| L2 Creativity | Novelty / Semantic Diversity / Narrative Diversity / Specificity / Surprise | 软门 | 报告 + 建议 |
| L3 Expression | Language / Style / Imagery / Dialogue / Rhythm | 软门 | 报告 + 建议（**L0 通过后才执行**） |

**执行顺序**：L0 → L1 → L2 → L3（L3 由 Style Agent / Final Editor 在最后）。

**铁律**：
- 禁止「人物逻辑 40 分 + 文笔 100 分 = 最终 85 分」的加权掩盖。
- L0 任一指标 FAIL → 直接 REJECT，无论 L1-L3 多高。
- L0 的 FAIL 只能通过「回退到人物/剧情设计阶段」修复，**禁止**通过金句/形容词/意象/悲情/象征/情绪修复（见 04 §3.3）。

---

## 2. L0 四指标定义

### 2.1 CVI —— Character Value Integrity（详见 04 §3）

8 项加权 + CRITICAL 失败类型一票否决。

### 2.2 CAI —— Character Agency Integrity（详见 04 §5）

检测 5 类强制行动：`PLOT_FORCED_ACTION / THEME_FORCED_ACTION / EMOTION_FORCED_ACTION / AUTHORIAL_FORCED_ACTION / COINCIDENCE_DEPENDENCY`。
"为了让故事更感人" → 直接 FAIL。

### 2.3 CCI —— Causal Coherence Integrity

```yaml
CCI 检查项:
  - causal_chain:      重要事件是否可串成 A→B→C→D（无 causal leap）
  - necessity_source:  B、C 是否具有角色（价值/决策）或环境（世界规则）必然性
  - missing_motivation: 是否有行为无动机
  - coincidence_overload: 巧合密度（重大转折依赖巧合 → 扣分；≤1 次/书 为容忍线）
  - forced_twist:      反转是否由人物选择或环境必然性产生
  - retroactive_justification: 是否事后补解释（"其实他早就…"）
  - plot_convenience:  剧情方便（恰好有人路过/恰好手机没电）
CCI >= 0.85 → PASS
```

### 2.4 WCI —— World Consistency Integrity

```yaml
WCI 检查项:
  - rule_preservation: 世界规则是否前后一致（IMMUTABLE 未被破坏）
  - timeline_consistency: 时间线自洽（日期/时刻/先后）
  - knowledge_consistency: 角色知识边界（谁不知道什么）
  - location_consistency: 地点连续性（桥在城东就不能在城西）
  - fact_consistency: 事实记忆（人物记得的事前后一致）
WCI >= 0.90 → PASS
```

---

## 3. L1 / L2 / L3 软门指标

### L1 Narrative
| 指标 | 含义 |
|---|---|
| Conflict | 冲突是否真实（价值/资源/信息/关系层面，非口角式） |
| Arc | 弧线是否有过程（S0→S4 不跳步） |
| Pacing | 节奏（信息释放/场景长度/章节钩子） |
| Meaning | 意义是否涌现（非说教） |
| Emotional Authenticity | 情绪是否来自人物处境而非套路 |

### L2 Creativity
| 指标 | 含义 |
|---|---|
| Novelty | 设定/情节新颖度（对照语义池与套路库） |
| Semantic Diversity | 语义方向多样性（防第一联想垄断，见 07 §7） |
| Narrative Diversity | 叙事模式多样性（冲突类型/场景类型/信息类型不重复） |
| Specificity | 具体性（职业细节/数字/感官细节，反"空泛形容词"） |
| Surprise | 意外性（信息意外，非巧合意外） |

### L3 Expression
| 指标 | 含义 |
|---|---|
| Language | 语言准确性/表现力 |
| Style | 风格一致性（对接现有 writing_style 池） |
| Imagery | 意象有效性与克制（防象征过载） |
| Dialogue | 对白辨识度（贴合人物） |
| Rhythm | 节奏与句式变化 |

---

## 4. Diagnostic Report（机器可读诊断）

每次 L0 FAIL 必须产出以下结构（JSON），**禁止**只输出"人物不够深刻"：

```json
{
  "status": "REJECT",
  "metric": "CVI",
  "score": 0.42,
  "threshold": 0.85,
  "failure_type": "CHARACTER_VALUE_HIERARCHY_COLLAPSE",
  "severity": "CRITICAL",
  "chapter_no": 7,
  "evidence": [
    {
      "text": "通车那天他没去剪彩，因为想起亡妻。",
      "text_anchor": "ch7/para-12",
      "reason": "行为解释仅引用情绪触发器(亡妻)，最高价值(professional_ethics 0.93)缺席"
    }
  ],
  "character_value": {
    "character": "陈工",
    "declared_hierarchy": {"public_duty": 1.0, "professional_ethics": 0.93, "family": 0.75},
    "effective_hierarchy_in_action": {"family": 0.75 → 1.0, "professional_ethics": 0.93 → 0}
  },
  "action": {"text": "缺席剪彩", "trace_available": false},
  "motivation_trace": {
    "worldview": "工程质量即生命",
    "value": "professional_ethics",
    "mission": "守住这座桥",
    "goal": null,
    "situation": null,
    "conflict": null,
    "decision": "由情绪触发器直接驱动",
    "broken_at": "goal → action（动机链断裂）"
  },
  "violations": [
    {"rule": "Value Preservation", "detail": "行为违反最高价值且无冲突剧情"},
    {"rule": "Emotional Override", "detail": "情绪触发器取代价值决定重大行为"}
  ],
  "counterfactual": {
    "drop_emotion_object": false,
    "drop_theme": true,
    "change_profession": false
  },
  "repair_strategy": [
    {"stage": "value_architect", "action": "重建行为动机：将职业责任作为行为主因"},
    {"stage": "scene_writer", "action": "妻子进入情感层：剪彩日触发回忆，作为内在冲突而非行为原因"},
    {"stage": "causal_planner", "action": "补因果：缺席剪彩的剧情必要性（复检报告/桥梁隐患）"}
  ],
  "retry_budget": {"used": 1, "max": 2}
}
```

### 诊断输出约束
1. **必须机器可读**：`failure_type` 从字典取（04 §4），不自由发挥。
2. **必须可定位**：每条 violation 有 `text_anchor`（章节/段落/句子）。
3. **必须可执行**：`repair_strategy` 明确"回退到哪个阶段、修什么"。
4. **必须可追溯**：记录 retry 预算与 repair 历史。

---

## 5. 门禁执行流程（在现有代码中的落点）

```
generate_chapter 当前:  provider.generate → 落库 done
升级后:
  provider.generate → 草稿（status=draft，不进正文）
  → State 抽取（正文 → state_delta）
  → 确定性检查（零成本预检：时间线/事实/长度/重复句）
  → L0 Critic 门（CVI/CAI/CCI/WCI）
      ├─ PASS → L1/L2 软门报告 → 落库 done + Quality Report
      └─ FAIL → Diagnostic → Repair（08）→ 重跑 → 预算内 or HUMAN_REVIEW_REQUIRED
```

**前端展示**：`Creative Quality Report`（需求二十八）随章节返回：
```json
{
  "character_value_integrity": 0.91,
  "character_agency": 0.88,
  "causal_integrity": 0.9,
  "world_consistency": 0.95,
  "semantic_diversity": 0.72,
  "narrative_diversity": 0.68,
  "emotional_authenticity": 0.81,
  "theme_emergence": 0.77,
  "cliche_risk": 0.12,
  "style_risk": 0.09,
  "critical_issues": [], "major_issues": [], "minor_issues": [],
  "repair_history": [{"round": 1, "issue": "…", "fixed": true}],
  "final_status": "PASS"
}
```

---

## 6. 预算与终止

| 预算 | 值 | 行为 |
|---|---|---|
| Repair 轮数上限 | 2（可配置） | 超限 → `HUMAN_REVIEW_REQUIRED`，章节 status=review，不落正文 |
| L0 重跑上限 | 与 Repair 同轮 | 同左 |
| 单章 LLM 调用上限 | 12（可配置） | 超限强制中断 + 审计 |
| 失败升级 | 连续 3 项目 FAIL | 进入人工审查队列 + 告警（复用现有 inspection_report 机制） |

**绝不允许**：无限重生成（成本失控 + 掩盖问题）。
