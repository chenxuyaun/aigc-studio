# 08 · 修复管道（REPAIR PIPELINE）

> Generate → Extract State → Validate → Critic → Diagnostic → Repair Plan → Localized Repair → Revalidate → PASS → Style Polish

---

## 1. 循环总览

```
      ┌──────────────────────────────────────────────────────────────┐
      │                                                              │
      ▼                                                              │
① Generate ──► ② Extract State ──► ③ Deterministic Check ──► ④ Critic(L0)
                                                                     │
                                                    PASS ──► ⑤ Style Polish ──► 输出 + Quality Report
                                                                     │
                                                    FAIL ──► ⑥ Diagnostic Report
                                                                     │
                                                    ┌────────────────┤
                                                    ▼                │
                                              ⑦ Repair Plan         │
                                                    ▼                │
                                              ⑧ Localized Repair ──┘ (重跑 ①-④)
                                                    │
                          retry 预算耗尽 ──► ⑨ HUMAN_REVIEW_REQUIRED
```

### 关键不变式

1. **Repair 只修被诊断的问题**：拿 Diagnostic 的 `evidence[].text_anchor` + `repair_strategy`，修完再验证。
2. **不允许全章重写绕过诊断**：Repair Agent 若输出与原文差异过大（>40% 行级 diff 且非诊断范围）→ 拒绝。
3. **每轮都有新诊断**：Repair 后重跑完整 L0（不是只查修复点）。
4. **预算硬顶**：`retry_budget.used >= max` → 停止，转人工。

---

## 2. 各阶段定义

### ① Generate
Scene Writer 按 07 §1 产出正文 + state_delta 提案。status=draft。

### ② Extract State
确定性抽取：从正文提取 facts/timeline/deltas，与 writer 的 state_delta 声明**交叉验证**
（声明必须有正文锚点；锚点缺失 → 该声明视为无效，不进 State）。

### ③ Deterministic Check（零 LLM）
时间线/事实/重复句/套路词/巧合计数/风格权限（见 07 §3.1）。
确定性 FAIL（如时间线矛盾）→ 直接进 Diagnostic，不浪费 LLM Critic 预算。

### ④ Critic（L0）
CVI / CAI / CCI / WCI 四检查器（独立视角）。任一 < 阈值 → FAIL。

### ⑤ Style Polish
仅 L0 PASS 后执行。Style Agent 改 FLEXIBLE 层 → style_diff_checker 校验 → 存 style 版本。

### ⑥ Diagnostic Report
机器可读（06 §4 schema）：failure_type / severity / evidence(text_anchor) / violations / repair_strategy / retry_budget。

### ⑦ Repair Plan
由 Diagnostic 自动生成（确定性映射 failure_type → 回退阶段 + 修复动作模板），Repair Agent 细化。

### ⑧ Localized Repair
Repair Agent 只动诊断区段，输出修复后 Scene + 更新 state_delta → 重跑 ①-④。

### ⑨ HUMAN_REVIEW_REQUIRED
- 连续 2 轮 Repair 后仍 FAIL；
- 或任一轮发现 CRITICAL 结构性错误（如人物价值与行为根本性矛盾，无法局部修）；
- 或 budget 耗尽。
→ 章节 status=review，正文不落库，进人工审查队列（复用 inspection_report 机制 + 前端高亮）。

---

## 3. failure_type → 修复阶段映射（确定性）

| failure_type（04 §4） | 回退阶段 | 修复动作模板 |
|---|---|---|
| CHARACTER_VALUE_HIERARCHY_COLLAPSE | Value Architect | 重建行为动机链：价值作为主因，情绪触发器降为内在冲突层 |
| MOTIVATION_DOWNGRADE | Character Architect | 补 Constitution 深度（使命/决策规则/历史），重写行为解释 |
| EMOTIONAL_OVERRIDE | Value Architect + Scene Writer | 分离情绪触发器与价值；场景内情绪反应保留但重大行为改由价值驱动 |
| THEME_FORCED_ACTION | Narrative Planner | 改主题表达为人物选择产物；或换人物（该价值更契合者） |
| PLOT_FORCED_ACTION | Causal Planner | 补因果链：为行为铺设角色/环境必然性 |
| AUTHORIAL_FORCED_ACTION | Scene Writer | 删叙述者解释腔，改为场景化呈现 |
| COINCIDENCE_DEPENDENCY | Causal Planner | 换掉巧合，改为人物决策或环境压力 |
| MISSING_MOTIVATION | Scene Writer | 补动机场景（价值被激活的时刻） |
| VALUE_FLIP_WITHOUT_PROCESS | Value Architect | 拆权重变化为多场景渐变 |
| UNMOTIVATED_EPIPHANY | Scene Writer | 补认知变化过程（S1→S2） |
| GENERIC_CHARACTER | Character Architect | 让职业/价值参与行为设计 |
| CAUSAL_LEAP | Causal Planner | 补中间节点（B、C 及必然性来源） |
| FORCED_TWIST | Causal Planner | 反转改由人物选择/信息揭示驱动 |
| THEME_EXPOSITION | Scene Writer | 说教句删改，主题留给读者推导 |
| EMOTIONAL_SHORTCUT_WARNING | Scene Writer | 套路元素改为与人物价值/历史真正相关 |

---

## 4. Repair 的三种粒度

| 粒度 | 适用 | 示例 | 成本 |
|---|---|---|---|
| delta 级 | state_delta 声明与正文不符 | 补锚点/改声明 | 零 LLM（确定性） |
| 段落级 | 局部逻辑/动机问题 | 重写某段行为解释 + 补动机场景 | 1 次 LLM |
| 场景级 | 结构性冲突（价值矛盾） | 重排本场景的事件顺序 | 1-2 次 LLM + 重验 |

**禁止**：全书级重写。结构性冲突 → 转 ⑨ 人工，不自动重写全书。

---

## 5. 修复质量度量

- **修复通过率**：repair round 通过率（目标 ≥ 60% 一轮通过）。
- **修复回归率**：修复 A 处是否引入 B 处新问题（L0 重跑全量检测，不只看 A）。
- **局部性**：修复 diff 是否局限于诊断区（行级 diff 度量）。
- **成本**：每章平均 LLM 调用数与 token（防预算失控）。

---

## 6. 在现有代码中的落点

```
现有:
  generate_chapter → 直接落库 done

升级（保留旧行为开关）:
  generate_chapter(draft_mode=True):
    content = writer(...)
    state_delta = extract_state(content)
    if not deterministic_check(state_delta, ...): return diagnostic(...)
    verdict = critic_l0(content, constitution, state)
    if verdict.fail:
        for round in range(repair_budget):
            diagnostic = make_diagnostic(verdict)
            content = repair_agent(content, diagnostic)
            verdict = critic_l0(content, ...)
            if verdict.pass: break
        else: return HUMAN_REVIEW_REQUIRED
    style = style_agent(content)
    persist(chapter, state_delta, quality_report)

配置开关:
  CREATIVE_ENGINE_ENABLED=false 时保持现有直通行为（灰度/回滚）
```

---

## 7. 与连载自动生成的结合

`serial_tick`（每 10 分钟自动产章）**必须**接入管道：

- 自动生成章节同样走 L0；FAIL 2 轮后 → status=review + 通知（复用现有告警）。
- 连续 3 章 HUMAN_REVIEW_REQUIRED → 自动暂停连载调度（复用现有 fail_count 暂停机制）。
- 目的：缺陷不被自动放大（修复风险 R1）。
