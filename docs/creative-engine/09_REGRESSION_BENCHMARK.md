# 09 · 回归基准（REGRESSION BENCHMARK）

> 像软件工程一样测试创作系统。每次修改 Prompt / Agent / 模型路由 / 质量门后自动回归。

---

## 1. 基准架构

```
regression/
├─ golden_cases.yaml        # 50 个 Golden Cases（输入 + 期望判定 + 允许行为）
├─ unit_tests/              # 14 个创作单元测试（确定性 + LLM 混合）
│   ├─ test_character_value_integrity.py
│   ├─ test_character_agency.py
│   ├─ test_motivation_trace.py
│   ├─ ...（见 §4）
└─ runner.py                # 批量执行 + 报告（PASS/FAIL/REGRESSION）
```

**执行触发**：
- 修改任何 Prompt / Agent / 模型路由 / 质量门阈值 → 必跑；
- CI（现有 pytest 流程）挂 `@pytest.mark.creative_benchmark`，默认跑确定性部分，LLM 部分打 `@pytest.mark.creative_llm`（按需/夜间跑）。

**判定方式**：
- 确定性检查器（cliche 检测/时间线/计数）→ 纯函数断言；
- LLM 检查器 → Golden Case 带"期望判定"，断言输出 JSON 的 failure_type/score 落在期望区间。

---

## 2. REGRESSION_CASE_001 ·「桥的名字」（用户指定，最高优先级）

```yaml
id: REGRESSION_CASE_001
title: 有信仰的守桥人（防止人物价值降维）
setup:
  character: 陈工，守桥人，工程建设 30 年，有信仰
  core_values: [责任, 工程伦理, 公共安全, 人民利益]
  value_hierarchy: {public_duty: 1.00, responsibility: 0.95,
                    professional_ethics: 0.93, family: 0.75,
                    personal_emotion: 0.65, reputation: 0.30}
  relationship: 妻子（已故，情感层/历史层/内在冲突层）
  scene: 大桥通车典礼，主角缺席剪彩

test:
  # 输入给 Scene Writer 或给 CVI checker 的待检正文
  - scenario_a (典型错误):
      text: "通车那天他没去剪彩，因为想起亡妻。"
      expect: FAIL
      failure_type: CHARACTER_VALUE_HIERARCHY_COLLAPSE
      note: 妻子成为主要行为原因，职业使命/责任/工程伦理消失
  - scenario_b (正确方向):
      text: "通车那天他没去剪彩。剪彩前夜，3 号墩的复检数据出来了——
            他带着报告去了桥墩现场。只有走到桥中央时，他才想起
            妻子说过：桥通了，一起走一趟。他在桥中央站了一会儿，
            然后继续检查伸缩缝。"
      expect: PASS
      note: 行为主因 = 职业责任（复检）；妻子进入情感/历史层（桥中央回忆），
            作为内在冲突而非行为原因
  - checks:
      - 妻子不得成为主要行为原因
      - 职业使命/责任/工程伦理不得消失
      - 妻子只应进入情感层/历史层/内在冲突层

guard: 任何 Prompt / Agent / 模型改动不得使 scenario_b 的 PASS 退化为 FAIL
```

---

## 3. 50 个 Golden Cases（按缺陷类别）

> 每个 case：`id / 类别 / 输入 / 期望判定`。输入可以是"给生成器的主题"（期望生成质量）
> 或"给检查器的正文"（期望检测命中）。这里给出全部 50 个的主题式清单（详细数据放 golden_cases.yaml 实现时展开）。

### 一、人物降维（5）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 1 | GC-01 | 有信仰的守桥人（= REGRESSION_CASE_001 scenario_a） | FAIL: CVI 崩塌 |
| 2 | GC-02 | 法医主角，案件相关重大决定只用"想起女儿"解释 | FAIL: MOTIVATION_DOWNGRADE |
| 3 | GC-03 | 工程师主角一切行为动机 = 初恋 | FAIL: MOTIVATION_DOWNGRADE |
| 4 | GC-04 | 主角无职业/价值参与，任何剧情都能套上 | FAIL: GENERIC_CHARACTER |
| 5 | GC-05 | 替换关系对象（妻子→父亲→战友）故事完全不变 | FAIL: GENERIC_CHARACTER |

### 二、情绪套路（6）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 6 | GC-06 | "妻子死了→他一生等待"，无价值参与 | WARN: EMOTIONAL_SHORTCUT |
| 7 | GC-07 | 悲情标配（雨+旧照片+遗物+十年）四件套齐上 | WARN/FAIL: SHORTCUT_CLUSTER |
| 8 | GC-08 | 套路元素只渲染不参与叙事 | WARN |
| 9 | GC-09 | "他看着她的背影消失在雨里" 当深刻收尾 | WARN: SHORTCUT_AS_DEPTH |
| 10 | GC-10 | 套路元素与人物历史/价值真正相关 | PASS（不误杀） |
| 11 | GC-11 | 死亡作为随机事件（无因果铺垫） | FAIL: FORCED_DEATH |

### 三、主题强行植入（4）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 12 | GC-12 | "为了表现奉献，人物牺牲" 无价值链 | FAIL: THEME_FORCED_ACTION |
| 13 | GC-13 | "为了表现家国，放弃爱情" 无决策过程 | FAIL: THEME_FORCED_ACTION |
| 14 | GC-14 | 叙述者直接点题说教（"这就是责任的意义"） | WARN: THEME_EXPOSITION |
| 15 | GC-15 | 主题从人物冲突自然涌现 | PASS |

### 四、职业失真（4）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 16 | GC-16 | 医生做手术与职业流程相悖 | FAIL: WCI |
| 17 | GC-17 | 工程师行为与工程常识矛盾（隐患不上报）且无解释 | FAIL: WCI |
| 18 | GC-18 | 律师在程序性场合行为不符合程序 | FAIL: WCI |
| 19 | GC-19 | 职业细节真实且参与叙事（排水工程师×梅雨） | PASS |

### 五、价值观崩塌（4）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 20 | GC-20 | 最高价值人物无过程反转（一夜间变信仰崩塌） | FAIL: VALUE_FLIP_WITHOUT_PROCESS |
| 21 | GC-21 | 行为违反最高价值且无冲突剧情 | FAIL: CVI |
| 22 | GC-22 | 假两难（其实没冲突硬拗纠结） | FAIL/WARN: FALSE_DILEMMA |
| 23 | GC-23 | 价值权重渐变 + 铺垫充分的价值变化 | PASS |

### 六、强行反转 / 牺牲 / 死亡（5）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 24 | GC-24 | 反转无伏笔无因果（"其实他是卧底"） | FAIL: FORCED_TWIST |
| 25 | GC-25 | 反转由人物选择/信息揭示驱动 | PASS |
| 26 | GC-26 | 强行牺牲（无价值理由牺牲） | FAIL: PLOT_FORCED_ACTION |
| 27 | GC-27 | 死亡为悲剧而悲剧 | FAIL: FORCED_DEATH |
| 28 | GC-28 | 巧合驱动重大转折（恰好/刚好） | FAIL: COINCIDENCE_DEPENDENCY |

### 七、金句驱动 / 象征过载（4）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 29 | GC-29 | 金句与人物价值矛盾（为了金句改变人物） | FAIL: CVI |
| 30 | GC-30 | 同一意象反复出现且无意义演进（月亮出现 5 次） | WARN: SYMBOL_OVERLOAD |
| 31 | GC-31 | 意象与人物内心真实呼应且克制 | PASS |
| 32 | GC-32 | 堆砌形容词（深刻/感人/克制/有力量） | WARN: ADJECTIVE_STACKING |

### 八、第一联想 / 套路组合（4）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 33 | GC-33 | "烟雨朦胧"→ 第一联想：江南油纸伞 | WARN: COMMON_ASSOCIATION |
| 34 | GC-34 | 主题×职业×世界的独特交叉（排水工程师×梅雨×铁路限速） | PASS |
| 35 | GC-35 | 套路组合拳（雨+故乡+老屋+等待） | FAIL/WARN: CLICHÉ_CLUSTER |
| 36 | GC-36 | 语义方向多样性达标（≥3 方向） | PASS |

### 九、角色/剧情工具化（4）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 37 | GC-37 | 角色只为推动剧情存在（工具人，无价值参与） | FAIL: SWAPPABLE_CHARACTER |
| 38 | GC-38 | 工具人角色也有动机链 | PASS |
| 39 | GC-39 | 剧情为角色弧线服务（人物驱动故事） | PASS |
| 40 | GC-40 | 作者解释腔（"他之所以…是因为…"） | WARN: AUTHORIAL_EXPLANATION |

### 十、因果 / 时间线 / 记忆 / 世界规则（6）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 41 | GC-41 | A→D 因果跳跃（无中间环节） | FAIL: CAUSAL_LEAP |
| 42 | GC-42 | 时间线矛盾（昨天发生的说成上周） | FAIL: TIMELINE |
| 43 | GC-43 | 人物记忆错误（忘记已发生的关键事件） | FAIL: MEMORY_ERROR |
| 44 | GC-44 | 世界规则破坏（会飞的设定里突然不能飞） | FAIL: WCI |
| 45 | GC-45 | 伏笔未回收（open loop 超过 N 章） | WARN: LOOP_LEAK |
| 46 | GC-46 | 知识泄漏（不该知道的人知道） | FAIL: KNOWLEDGE_LEAK |

### 十一、风格压过故事 / 其他（4）
| # | id | 输入 | 期望 |
|---|---|---|---|
| 47 | GC-47 | 文笔华丽但因果/人物崩坏 | FAIL: L0（风格不救场） |
| 48 | GC-48 | 润色改变了事实（Style 层越权） | FAIL: STYLE_OVERRIDE |
| 49 | GC-49 | 对话所有人一个腔调 | WARN: DIALOGUE_HOMOGENEOUS |
| 50 | GC-50 | 无过程顿悟（突然醒悟） | FAIL: UNMOTIVATED_EPIPHANY |

---

## 4. 创作单元测试（14 个，规格）

| # | 测试 | 类型 | 断言要点 |
|---|---|---|---|
| 1 | `test_character_value_integrity` | 确定性+LLM | 给定 Constitution + 行为，CVI 分与失败类型正确；scenario_a→崩塌，scenario_b→PASS |
| 2 | `test_character_agency` | LLM | 五类强制行动识别（含"为了让故事感人"直判 FAIL） |
| 3 | `test_motivation_trace` | 确定性 | trace 链完整性校验（缺一环报 broken_at） |
| 4 | `test_causal_integrity` | 确定性+LLM | A→D 跳跃检出；必要性来源标注存在 |
| 5 | `test_theme_intrusion` | LLM | GC-12/13 检出；GC-15 放行 |
| 6 | `test_emotional_shortcut` | 确定性 | 词库命中 + 上下文规则（参与叙事 vs 替代深度） |
| 7 | `test_character_counterfactual` | LLM | Test A-E 判定正确（C/D/E 要求行为改变） |
| 8 | `test_relationship_substitution` | LLM | 关系对象替换后故事应改变 |
| 9 | `test_semantic_diversity` | 确定性 | 方向间距离分；第一联想惩罚触发 |
| 10 | `test_cliche_detection` | 确定性 | 词库+组合规则；GC-10 不误杀 |
| 11 | `test_story_state_consistency` | 确定性 | StateDelta 应用后 State 自洽（facts 无矛盾、loop 引用有效） |
| 12 | `test_timeline_consistency` | 确定性 | timeline.events 排序自洽 + 与章节号对应 |
| 13 | `test_world_rule_consistency` | 确定性 | IMMUTABLE 规则未被 delta 触碰 |
| 14 | `test_style_does_not_change_story` | 确定性 | style_diff_checker：变体与原文仅 L3 层差异 |

**运行方式**：`cd apps/api && uv run pytest -m creative_benchmark`（确定性全跑）；
`-m creative_llm`（LLM 部分，配置真实 provider 时跑）。

---

## 5. 真实模型联调记录（2026-08-18）

> 环境：本地 grok2api（:8000，主链路）+ cpa（:8317，备用，gpt-oss-120b-medium）
> 2026-08-18 主链路 grok2api 因 FlareSolverr 解 CF 挑战失败（`ERR_CONNECTION_CLOSED` / clearance_refresh_failed）
> 而 502——外部依赖故障；联调改走 cpa 真实模型完成。

| 验证项 | 输入 | 真实模型判定 | 结论 |
|---|---|---|---|
| CVI Critic（无 constitution） | scenario_a 亡妻句 | score=0.00 FAIL（GENERIC_CHARACTER） | ✅ 判定方向正确 |
| CVI Critic（带 constitution） | scenario_a 亡妻句 | score=1.00 **PASS（误判）** | ❌ 暴露 prompt 缺陷 |
| **修复后** CVI Critic（带 constitution） | scenario_a 亡妻句 | score=0.00 FAIL（**MOTIVATION_DOWNGRADE**），evidence：行为解释仅提及亡妻，未关联任何价值层级 | ✅ 桥的名字识别成功 |
| **修复后** CVI Critic | scenario_b 价值驱动 | score=1.00 PASS（无证据） | ✅ 不误杀 |
| Counterfactual | scenario_a | ok=True **downgraded=True**（drop_emotion_object=False） | ✅ 降维识别 |
| Semantic Explorer | 烟雨朦胧 | 湿地监测 / 玻璃幕墙 / 交通责任（score=0.88 ≥ 0.7） | ✅ 防第一联想（无江南油纸伞） |

**联调发现的 prompt 缺陷（已修复）**：
原 CVI prompt 检查"行为是否违反价值"→ 模型对中性行为（缺席剪彩）判 PASS。
修复：明确「重大行为 = 对人物/世界有影响的决定，即使表面中性」+「动机解释仅引用情感/关系对象而无价值支撑
→ MOTIVATION_DOWNGRADE / CHARACTER_VALUE_HIERARCHY_COLLAPSE」→ 判定正确。
**教训**：桥的名字检测的是**动机解释的降维**，不是行为本身的违规——prompt 必须精确对准这个判定目标。

---

## 6. 回归门槛（CI）

```
GOLDEN_CASE_PASS_RATE >= 0.95     # 50 例中至少 47 例符合期望
UNIT_TEST_PASS = 100%             # 14 个创作单元测试全过
REGRESSION_CASE_001 = PASS        # 桥的名字：scenario_a FAIL + scenario_b PASS 双断言
```

任何 Prompt/Agent/路由/门阈值修改后不达标 → 阻止合入（红门）。
