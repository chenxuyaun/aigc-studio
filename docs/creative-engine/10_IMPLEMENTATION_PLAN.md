# 10 · 实施计划（IMPLEMENTATION PLAN）

> 增量改造，不推翻现有系统。遵循：先理解 → 建模型 → 设计接口 → 增量改造 → 测试 → 验证 → 再重构。

---

## 0. 改造原则

1. **开关化**：`CREATIVE_ENGINE_ENABLED`（默认关）——存量链路（连载/手动生成/导演工作室）行为不变，新内核灰度接入。
2. **可回滚**：每阶段产出独立迁移 + 快照；Prompt 版本化。
3. **可观测**：`creative_runs` 审计表记录每次 Agent 调用 / PROPOSE / ACCEPT / REJECT / 成本。
4. **先确定性后 LLM**：能确定性检查的先落地（零成本、可单元测试），LLM 检查器随后。
5. **Golden Case 先行**：每个新检查器配 Golden Case 再上线（TDD 式）。

---

## 1. 阶段划分（P0 → P3）

### P0 · 状态基座（不动生成路径，纯增量）

> **状态：✅ 已完成（2026-08）** —— `app/creative/` 包落地，迁移 `c0ffee000001`。

| # | 任务 | 产出 | 验证 |
|---|---|---|---|
| P0-1 | 新增 `story_states` 表 + `StoryState` schema（05 §1） | ✅ 表 + pydantic schema（`app/creative/schemas.py`） | ✅ 迁移 + 单元测试 |
| P0-2 | `story_characters` 增加 `constitution` JSON 列 + Constitution schema（03 §2） | ✅ 列 + schema + 校验器 | ✅ test_constitution_* 全绿 |
| P0-3 | `story_characters` 增加 `value_hierarchy` 支持（并入 constitution） | ✅ Value Model schema（04 §1，并入 constitution） | ✅ 权重/顶部唯一/情绪分离校验 |
| P0-4 | 新增 `creative_runs` 审计表（run_id/agent/stage/action/verdict/cost） | ✅ 表 + 记录器（`creative_models.py`） | ✅ 迁移测试 |
| P0-5 | 新增 `creative_prompts` 版本表（prompt_key/version/content） | ✅ 表 + 加载器 | ✅ 迁移测试 |
| P0-6 | 迁移：`settings` 中 6+ 种语义拆出（compass/writing_style 留展示，其余进 State） | ⏳ 部分：store.py 已提供 StoryState 承载；settings 写回迁移留 P3 灰度 | - |

**P0 验收**：✅ 现有测试无回归；生成路径未动（CREATIVE_ENGINE_ENABLED 未引入）。

### P1 · 确定性检查器 + 状态校验（零 LLM，可测）

> **状态：✅ 确定性部分已完成（2026-08）** —— LLM 部分（Semantic Explorer 生成方向）留 P2。

| # | 任务 | 产出 | 验证 |
|---|---|---|---|
| P1-1 | StateValidator（05 §3.3）：tier/text-anchor/状态机/因果校验 | ✅ `state_validator.py`（validate_state_delta + apply_delta） | ✅ test_validator_* + test_apply_delta_* |
| P1-2 | cliché 检测器（07 §5）+ 套路词库 | ✅ `cliche_detector.py`（词库 31 条 + 集群/替代深度启发式） | ✅ test_shortcut_* |
| P1-3 | 时间线/事实检查器（查 StoryState） | ✅ `state_checks.py`（timeline/facts/knowledge/loops） | ✅ test_timeline_* / test_knowledge_leak / test_loop_leak |
| P1-4 | 语义多样性引擎（07 §7）：方向扩展 + 距离分 | ✅ `semantic_diversity.py`（共享词/字符混合相似度 + 第一联想判定） | ✅ test_diversity_* |
| P1-5 | style_diff_checker（07 §8.2） | ✅ `style_firewall.py`（数字/术语/时间词指纹 + n-gram 注入检测） | ✅ test_style_* |
| P1-6 | 生成前 Intent+Semantic 预检（接入 creation/plan 与 generate_outline） | ⏳ P2（需 Semantic Explorer LLM） | - |

**P1 验收**：✅ 14 个创作单元测试中确定性部分全部落地（35 个 creative 测试全绿）。

### P2 · LLM Critic + 质量门 + Diagnostic（核心升级）

| # | 任务 | 产出 | 验证 |
|---|---|---|---|
| P2-1 | CVI checker（04 §3，8 项 + 失败类型字典） | `critics/cvi.py` | test_character_value_integrity + GC-01/02/20/29 |
| P2-2 | CAI checker（04 §5） | `critics/cai.py` | test_character_agency |
| P2-3 | CCI checker + Causal Graph schema（05 §1） | `critics/cci.py` | test_causal_integrity |
| P2-4 | WCI checker（06 §2.4） | `critics/wci.py` | test_world_rule_consistency（LLM 部分） |
| P2-5 | Theme Guard（07 §4） | `critics/theme.py` | test_theme_intrusion + GC-12/13/15 |
| P2-6 | Counterfactual Test（07 §6） | `critics/counterfactual.py` | test_character_counterfactual + test_relationship_substitution |
| P2-7 | Diversity Critic（L2） | `critics/diversity.py` | GC-29/30/32 |
| P2-8 | Diagnostic Report 生成器（06 §4 schema + failure_type 映射） | `diagnostic.py` | schema 校验测试 |
| P2-9 | Repair Agent（08：局部修复 + diff 约束 + 预算） | `repair_agent.py` | 08 §4 三粒度测试 |
| P2-10 | 模型路由扩展（07 §9：role 字段 + 独立 critic 可选） | provider_resolver 增量 | 路由测试 |

**P2 验收**：14 个单元测试全绿；50 Golden Cases ≥ 47 PASS（LLM 部分以夜间回归跑）。

### P3 · 流水线接入（灰度）

> **状态：P3 全部 ✅（2026-08）** —— 生成/连载/MCP/前端/导演工作室全部接入；回归基准落地。

| # | 任务 | 产出 | 验证 |
|---|---|---|---|
| P3-1 | `generate_chapter` 增加 `draft_mode`（草稿→State→L0→落库/修复循环） | ✅ `app/services/story_gate.py` + story_forge 分支；`CREATIVE_ENGINE_ENABLED`/`CREATIVE_MAX_REPAIR_ROUNDS` 配置；L0 FAIL → status=review | ✅ test_draft_mode_* （PASS 落库 + QualityReport / 修复预算耗尽转 review） |
| P3-2 | `story_crew` 升级：editor→critic 入口、stagehand→状态机更新、consistency→State 基座 | ✅ editor 集成 CVI 确定性预检（`_cvi_precheck_for_chapter`）；stagehand/consistency 待后续增强 | ✅ crew 测试 |
| P3-3 | MCP 创作工具提案化（write_chapter 走 draft；update_character_state 加 schema） | ✅ write_chapter 写入后过确定性质量门（review/done + quality_report）；update_character_state 支持 CharacterState schema 校验 | ✅ test_write_chapter_quality_gate_review |
| P3-4 | 连载 `serial_tick` 接入 L0 + HUMAN_REVIEW_REQUIRED 暂停 | ✅ CREATIVE_ENGINE_ENABLED=1 时任务携带 draft_mode；review 章跳过 + 连续 3 次 tick 自动暂停 | ✅ test_serial_tick_review_pauses_after_3 / draft_mode |
| P3-5 | 前端：章节详情展示 Creative Quality Report + review 状态 | ✅ stream 端点确定性预检（`deterministic_quality_report`）+ ChapterEditor 质量报告面板 | ✅ tsc 通过 |
| P3-6 | AI 导演工作室接入：选角阶段生成 value_hierarchy，剧本阶段生成因果草稿 | ✅ plan 选角输出 value_hierarchy/core_values/mission/emotional_triggers；script 每场 beat 标注 driver（因果草稿）；publish 带 plan → story_characters 落 Character Constitution | ✅ test_constitution_from_plan_char / test_publish_with_plan_models_constitutions |

**P3 验收**：✅ 全量 pytest + tsc 全绿；`CREATIVE_ENGINE_ENABLED` 灰度开关验证；回归基准（golden_cases.yaml 50 例）落地。

---

## 2. 文件落点清单（新增/修改）

```
新增:
  apps/api/app/creative/
    ├─ schemas.py            # StoryState/Constitution/ValueModel/Diagnostic pydantic
    ├─ state_validator.py    # 05 §3.3
    ├─ state_checks.py       # 时间线/事实/知识泄漏确定性检查
    ├─ cliche_detector.py    # 07 §5
    ├─ semantic_diversity.py # 07 §7
    ├─ style_firewall.py     # 07 §8
    ├─ diagnostic.py         # 06 §4
    ├─ repair_agent.py       # 08
    ├─ critics/
    │   ├─ cvi.py / cai.py / cci.py / wci.py
    │   ├─ theme.py / diversity.py / counterfactual.py
    │   └─ __init__.py
    └─ pipeline.py           # 流水线编排（生成→验证→修复→输出）
  apps/api/tests/
    ├─ test_creative_benchmark.py   # 回归 runner
    ├─ test_*（14 个创作单元测试）
    └─ golden_cases.yaml（50 例）
  alembic/versions/          # P0 各迁移

修改（增量）:
  apps/api/app/models/story_character.py   # +constitution
  apps/api/app/models/story_project.py     # +story_states 关联（或新表）
  apps/api/app/services/story_forge.py     # draft_mode 分支
  apps/api/app/services/story_crew.py      # editor/stagehand/consistency 升级
  apps/api/app/mcp/server.py               # 创作工具提案化
  apps/api/app/services/creation_service.py# 选角/剧本接入建模层
  apps/api/app/services/provider_resolver.py # role 路由（可选）
  apps/api/app/core/config.py              # CREATIVE_ENGINE_ENABLED 等开关
```

---

## 3. creative_runs 审计表（字段草案）

```sql
CREATE TABLE creative_runs (
  id VARCHAR(36) PRIMARY KEY,
  project_id VARCHAR(36) NOT NULL,
  chapter_id VARCHAR(36),
  run_type VARCHAR(32),        -- chapter / outline / crew / plan / script
  stage VARCHAR(32),           -- writer / critic_cvi / repair / style / ...
  agent_role VARCHAR(32),
  action VARCHAR(16),          -- READ / PROPOSE / ACCEPT / REJECT / GENERATE
  verdict JSON,                -- {metric, score, threshold, failure_type}
  delta_json JSON,             -- 提案/变更内容
  model VARCHAR(100),
  tokens_used INT,
  cost_usd DECIMAL(8,4),
  created_at DATETIME,
  INDEX idx_creative_runs_project (project_id, chapter_id)
);
```

---

## 4. 灰度与回滚策略

| 维度 | 策略 |
|---|---|
| 功能开关 | `CREATIVE_ENGINE_ENABLED=false` 时，现有直通生成完全不变（零风险上线） |
| 用户级灰度 | 按 project.settings["engine_mode"] = legacy/draft/gated 三档逐步放开 |
| Prompt 回滚 | creative_prompts 版本表：prompt_key 指向版本号，出问题一键切回旧版 |
| 状态回滚 | story_states 快照随章节版本（05 §6），与 restore_chapter_version 联动 |
| 基准保护 | 每阶段结束跑全量回归；Golden Case 红门阻止合入 |

---

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 多 Agent 成本失控 | 调用预算（06 §6）+ creative_runs 记账 + 阈值告警 |
| LLM 检查器不稳定（误杀/漏杀） | 确定性优先 + Golden Case 锁行为 + critic 低温度 + failure_type 字典约束输出 |
| 状态迁移破坏存量数据 | P0 只加列不改读；迁移脚本 + 快照 |
| 连载自动放大缺陷 | serial_tick 接入 L0 + 自动暂停（08 §7） |
| 上游会话失效中断长流程 | 流水线每阶段可重入（进度落库）；中断恢复从最近 ACCEPT 继续 |

---

## 6. 里程碑

| 里程碑 | 内容 | 判定 |
|---|---|---|
| M1 | P0 + P1 完成 | 确定性检查器全绿，现有测试全绿，开关未开 |
| M2 | P2 完成 | 14 个创作单元测试 + 50 Golden Cases ≥ 95%，LLM critic 可用 |
| M3 | P3 完成 | 灰度开关全量接入，Quality Report 前端可见，全量回归绿 |
| M4 | 稳定期 | 连续 2 周无回归；CREATIVE_ENGINE_ENABLED 默认开（可配） |

---

## 7. 验收对照（需求三十）

M2 达成即满足 1-8（第一联想/价值层级/动机链/降维识别/情绪捷径/主题强迫/反事实/因果断裂），
M3 达成即满足 9-18（StoryState/CharacterState/生成中质检/诊断/局部修复/再验证/L0 硬门/润色顺序/回归基准/指标测试）。
