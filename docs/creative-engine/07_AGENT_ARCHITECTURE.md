# 07 · Agent 架构（AGENT ARCHITECTURE）

> 从"一个 Agent 干完所有事"升级为"专职分工 + 独立批判 + 状态总线约束"的创作流水线。

---

## 1. Agent 角色总表（15 个）

| # | Agent | 职责 | 输入 | 输出 | 权限（State Bus） |
|---|---|---|---|---|---|
| 1 | **Intent Agent** | 澄清创作意图：主题边界/用户目标/禁止联想 | 用户主题 | Intent Spec | READ |
| 2 | **Semantic Explorer** | 语义扩展：多方向联想 + 多样性评分 | Intent Spec | Semantic Directions | READ |
| 3 | **Character Architect** | 建立每人 Character Constitution | 方向 + 用户素材 | Constitution（03） | PROPOSE（新建） |
| 4 | **Value Architect** | 建立价值层级 + 决策规则 + 动机链模板 | Constitution | Value Model（04） | PROPOSE（新建） |
| 5 | **World Architect** | 世界规则/时间线骨架/机构/知识状态 | 方向 | World Spec | PROPOSE（新建） |
| 6 | **Narrative Planner** | 全书弧线 + 章节点 + 悬念管理 | 全部建模 | Story Plan | PROPOSE |
| 7 | **Causal Planner** | 因果图草案（事件链 + 必然性来源标注） | Story Plan | Causal Graph | PROPOSE |
| 8 | **Scene Writer** | 写场景草稿 + StateDelta 提案（**不评价自己**） | Plan + State 子集 | Scene + Delta | PROPOSE |
| 9 | **Character Critic** | CVI/CAI 检查（人物成立性） | Scene + Constitution | Verdict + Evidence | READ |
| 10 | **Causal Critic** | CCI 检查（因果连贯） | Scene + Causal Graph | Verdict + Evidence | READ |
| 11 | **Theme Critic** | 主题入侵检测 + 主题涌现评估 | Scene + Theme State | Verdict + Evidence | READ |
| 12 | **Diversity Critic** | L2 检查（新颖/多样/具体/意外） | Scene + 语义池 | Verdict + Evidence | READ |
| 13 | **Repair Agent** | 按 Diagnostic 局部修复（只动被诊断处） | Diagnostic + Scene | 修复后 Scene + Delta | PROPOSE |
| 14 | **Style Agent** | 仅 FLEXIBLE 层润色（语言/节奏/意象） | L0 通过的 Scene | Style 变体 | READ + FLEXIBLE |
| 15 | **Final Editor** | 终审 + 拼装输出（**L0 全过才工作**） | 全量 | 定稿 + Quality Report | READ |

**角色铁律**：
- Writer 不评价自己（无自评 prompt）。
- Critic 不重写全文（只出 Verdict + Evidence + 定位）。
- Repair Agent 只修改被诊断的问题（不做全面重写）。
- Final Editor 只能在所有 L0 Gate 通过之后工作。

---

## 2. 现有 story_crew 的升级映射

| 现有 Agent | 升级为 | 关键变化 |
|---|---|---|
| director | Narrative Planner 的轻量版 | 输出改为结构化（本场目标/冲突/悬念意图），存 Story Plan 而非 settings["direction"] |
| writer | Scene Writer | 产出正文 + state_delta 提案；不再直接落库 done |
| editor | Character Critic + Causal Critic 入口 | 输出 Verdict + Evidence（JSON），不再存"审校报告文本" |
| stagehand | State Validator 的提案来源 | 按状态机阶段更新，双写 current_state 文本 |
| consistency | CCI + WCI 全书级检查 | 确定性检查（查 State）+ LLM 兜底 |

---

## 3. Critic 检查器（LLM + 确定性混合）

### 3.1 确定性检查器（零 LLM 成本，先跑）

| 检查器 | 实现 | 检测 |
|---|---|---|
| `cliche_detector` | 套路词库 + 上下文规则 | 雨/旧照片/旧信/遗物/死亡/故乡/十年/孤独/等待/老屋/桥/船/黄河/唢呐/灯/月/背影/墓碑/未寄出的信… |
| `style_firewall` | 字段权限检查 | Style 输出是否触碰 State（禁止） |
| `timeline_checker` | 查 StoryState.timeline | 时间矛盾 |
| `fact_checker` | 查 StoryState.facts | 事实矛盾/记忆错误 |
| `coincidence_counter` | 事件类型统计 | 巧合密度 |
| `repetition_detector` | n-gram 相似度 | 句子/场景/意象重复 |
| `diversity_counter` | 语义向量/词表 | 语义多样性分（07 §7） |

### 3.2 LLM 检查器（独立 prompt 角色，与 writer 不同视角）

| 检查器 | 输入 | 输出（严格 JSON） |
|---|---|---|
| CVI checker | Scene + Constitution + 当前价值权重 | {score, failure_types[], evidence[], counterfactual{}} |
| CAI checker | Scene + 重大行为清单 | {forced_action_types[], count, score} |
| CCI checker | Scene + Causal Graph | {leaps[], missing_motivations[], score} |
| Theme checker | Scene + Theme State | {theme_intrusions[], emergence_score} |
| WCI checker | Scene + World Spec | {violations[], score} |

**模型路由**：Critic 可用独立模型（若配置）或同模型低温度（temperature=0.2），但**必须与 writer 的调用在上下文上分离**（writer 不携带 critic 视角，critic 不携带 writer 的自我辩解）。

---

## 4. Theme Guard（主题守卫）

### 4.1 原则

> 主题应该通过人物选择**产生**，而不是人物为了表达主题而行动。

### 4.2 Theme Intrusion Detector

检测 `THEME_FORCED_CHARACTER_ACTION`：

| 模板 | 触发 |
|---|---|
| 为了表现奉献，所以人物牺牲 | THEME_FORCED_ACTION |
| 为了表现爱，所以人物等待十年 | THEME_FORCED_ACTION + 情绪捷径 |
| 为了表现家国，所以人物放弃爱情 | THEME_FORCED_ACTION（除非动机链成立） |

**继续追问**（检测到模板后强制）：
1. 为什么这个人物会做这个选择？
2. 这个选择是否来自他的价值结构（decision_rules）？
3. 换一个没有该价值的角色，是否还会这么选？（不会 → 成立；会 → 主题注入）

### 4.3 主题涌现评分

```
emergence_score = 主题被人物价值冲突驱动的程度（0-1）
  = 主题证据中"由人物决策产生"的比例
  vs 主题证据中"叙述者直接点题/说教"的比例
```

- 涌现 ≥ 0.6 → 健康（主题自然浮现）
- 叙述者点题占比高 → 触发 `THEME_EXPOSITION` 告警（说教化）

---

## 5. Emotional Shortcut Detector（情绪捷径检测）

### 5.1 词库（高频套路元素）

雨 / 旧照片 / 旧信 / 遗物 / 死亡 / 故乡 / 十年 / 孤独 / 等待 / 老屋 / 桥 / 船 / 黄河 / 唢呐 / 灯 / 月 / 背影 / 墓碑 / 未寄出的信 / 台阶 / 炊烟 / 老槐树 / 手绢 / 车站 / 老街 / 黄昏 / 麦田 / 雪地脚印 …

### 5.2 检测规则（不是禁止，是"替代验证"）

```
命中套路元素时:
  level-1 轻提示:  该元素是否作为人物深度的替代品出现？（只出现没参与叙事）
  level-2 警告:    "妻子死了→他一生等待" 式写法 → EMOTIONAL_SHORTCUT_WARNING
  level-3 FAIL:    套路元素成为重大行为的唯一动机来源（→ CVI·Emotional Override）
```

**必须验证**（套路元素出现时）：人物价值/职业/使命/历史/选择/行动**是否真正参与叙事**。
只有渲染没有参与 → 警告；参与但只作点缀 → 放行；替代深度 → FAIL。

---

## 6. Counterfactual Character Test（反事实人物测试）

| Test | 操作 | 通过标准 |
|---|---|---|
| A | 删除核心情感对象 | 重大行为仍成立（价值支撑） |
| B | 删除主题 | 重大行为仍成立 |
| C | 改变职业 | 行为**改变**（职业参与模型） |
| D | 改变价值层级 | 行为**改变**（价值参与模型） |
| E | 替换关系对象（妻子→父亲→母亲→战友→老师） | 故事**改变**（关系参与模型） |

- A/B 失败 → 人物降维（MOTIVATION_DOWNGRADE）。
- C/D/E 失败（完全不变）→ 人物职业/价值/关系未进入模型（GENERIC_CHARACTER）。

**实现**：LLM 变体评估（给 Critic 一个变体问题，评估行为是否仍成立/是否改变），
由 CVI checker 输出 `counterfactual{}` 块（见 06 §4 示例）。

---

## 7. Semantic Diversity Engine（语义多样性引擎）

### 7.1 防第一联想垄断

```
用户输入: "烟雨朦胧"
✗ 立即生成: 江南/油纸伞/青石板/旧桥/小船/旗袍/茶馆/离愁/故人
✓ 先 Semantic Expansion（≥3 个语义方向）:
   自然(江南烟雨) / 工业(梅雨限速/排水工程) / 工程(桥梁伸缩缝) / 医学(法医现场)
   交通(铁路调度) / 农业(灌溉) / 城市(雨水回收) / 地质灾害(山区滑坡) ...
```

### 7.2 实现

1. **Semantic Explorer**：输入 Intent，输出 N 个语义方向（每方向含关键词/设定钩子/职业钩子）。
2. **Semantic Diversity Score**：计算候选方向的**分布距离**（embedding 或词表 Jaccard 反比）。
3. **第一联想惩罚**：若某方向与输入词的关联度过高且与其他方向距离过近 → 提示"换一个方向"。
4. **交叉点搜索**：主题 × 人物 × 职业 × 世界 的独特交叉（如"雨季 × 城市排水工程师 × 铁路限速"），拒绝"猎奇式"替代。

### 7.3 阈值

```
Semantic Diversity Score >= 0.5（方向间平均距离）→ PASS
命中 COMMON_ASSOCIATION（第一联想）→ 要求重构
```

---

## 8. Style Firewall（风格防火墙）

### 8.1 权限边界

```
Style Agent 只能修改（FLEXIBLE 层）:
  - 语言 / 节奏 / 句式 / 意象 / 修辞 / 叙述声音

Style Agent 不得修改:
  - 人物价值 / 人物目标 / 人物因果 / 人物行为 / 世界规则 / 时间线
```

### 8.2 机制

1. **接口隔离**：Style Agent 的输入是"正文文本 + 风格指令"，输出是"文本变体"；
   **无权调用任何 State 写入接口**（物理隔离，非 prompt 约束）。
2. **差异校验**：`style_diff_checker` 对比原文与变体——仅允许 L3 层差异；
   若变体改变了事实/价值/因果 → REJECT 变体。
3. **版本化**：风格变体存 `story_chapter_versions`（note="style"），不覆盖正文主版本。

---

## 9. 模型路由（Model Routing）

### 9.1 现状与问题

`resolve_text_provider(db, model)` 全局单模型；writer/critic/director 同模型同温度。
问题：同一模型"自己写自己审"必然自我印证（D5）。

### 9.2 目标路由

```yaml
model_routing:
  writer:      primary_model          # grok-4.5 或用户指定（默认）
  critic:      critic_model|primary   # 配置了独立模型用独立；否则同模型 temperature=0.2
  planner:     primary_model
  repair:      primary_model
  style:       primary_model (temperature 0.8)
  extractor:   cheap_model|primary    # 状态抽取/确定性检查的 LLM 部分可降级

路由键: 按 agent_role × task_type，ProviderConfig 增加 role 匹配字段（增量，不动现有解析）
```

### 9.3 约束

- 模型路由是**可选增强**，默认同模型也能跑（独立 prompt + 低温度 + 上下文隔离已显著改善）；
- 若配置了独立 critic 模型，必须满足"critic 的 prompt 不含 writer 的自我辩解"。

---

## 10. 工具与 Harness（Agent Harness 层）

### 10.1 现状

- `_chapter_tool_loop`（MCP 工具循环，默认关）：模型可调用 read_bible/write_chapter/update_character_state/list_outline。
- 问题：工具直写 DB（write_chapter 直接落库 done；update_character_state 无 schema 校验）。

### 10.2 升级

| 工具 | 升级 |
|---|---|
| `read_bible` | 改为读 StoryState（返回结构化，含 value_hierarchy/state_delta 摘要） |
| `write_chapter` | 改为**提案模式**：写入 draft 状态，必须过 State Validator + L0 门才转 done |
| `update_character_state` | schema 校验（stage ∈ S0-S4、value_weights、active_conflict） |
| `list_outline` | 返回计划型大纲（与事实分离，修复 D17） |
| `check_story_consistency` | 升级为 CCI+WCI 检查器入口 |

### 10.3 Harness 职责（新增）

- **状态注入**：每轮生成前，把相关 State 子集（不是全文）注入上下文（token 预算控制）。
- **工具白名单**：按 Agent 角色限制可用工具（writer 可读 bible/写提案；critic 只读）。
- **调用预算**：每 Agent 工具调用次数/轮次上限（防失控循环）。
- **审计**：所有 PROPOSE/ACCEPT/REJECT + 调用链入 `creative_runs`。
