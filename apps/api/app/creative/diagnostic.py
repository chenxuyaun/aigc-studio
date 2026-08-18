"""Diagnostic Report 生成器（06 §4 + 08 §3 的确定性部分）。

- failure_type → repair_strategy 映射（08 §3 表格落地）：回退阶段 + 修复动作模板
- make_diagnostic：从 Critic 判定组装机器可读 DiagnosticReport
- 本模块零 LLM；Critic 的判定输入由 LLM 检查器产出（P2 接入）
"""

from __future__ import annotations

from app.creative.schemas import (
    DiagnosticEvidence,
    DiagnosticReport,
    FailureType,
    GateVerdict,
    MetricName,
    RepairStrategy,
    RetryBudget,
    Severity,
)

# failure_type → (回退阶段, 修复动作模板, 严重度)（08 §3）
_REPAIR_MAP: dict[FailureType, tuple[str, str, Severity]] = {
    FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE: (
        "value_architect",
        "重建行为动机链：价值作为行为主因，情绪触发器降为内在冲突层（不得作为行为原因）",
        Severity.CRITICAL,
    ),
    FailureType.MOTIVATION_DOWNGRADE: (
        "character_architect",
        "补 Constitution 深度（使命/决策规则/历史），重写行为解释为价值驱动",
        Severity.CRITICAL,
    ),
    FailureType.EMOTIONAL_OVERRIDE: (
        "value_architect",
        "分离情绪触发器与核心价值：即时反应保留情绪，重大行为改由价值驱动",
        Severity.HIGH,
    ),
    FailureType.THEME_FORCED_ACTION: (
        "narrative_planner",
        "主题改为人物选择产物；或更换人物为该价值更契合者",
        Severity.CRITICAL,
    ),
    FailureType.PLOT_FORCED_ACTION: (
        "causal_planner",
        "补因果链：为行为铺设角色/环境必然性，删除剧情便利",
        Severity.CRITICAL,
    ),
    FailureType.AUTHORIAL_FORCED_ACTION: (
        "scene_writer",
        "删除叙述者解释腔，改为场景化呈现（行为由情境与价值显式推出）",
        Severity.HIGH,
    ),
    FailureType.COINCIDENCE_DEPENDENCY: (
        "causal_planner",
        "换掉巧合：重大转折改由人物决策或环境压力驱动",
        Severity.HIGH,
    ),
    FailureType.MISSING_MOTIVATION: (
        "scene_writer",
        "补动机场景：价值被情境激活的时刻（Motivation Trace 补全 goal/situation 环节）",
        Severity.HIGH,
    ),
    FailureType.VALUE_FLIP_WITHOUT_PROCESS: (
        "value_architect",
        "价值权重变化拆为多场景渐变（每章 ≤0.05），弧线终点大改需多场景铺垫",
        Severity.HIGH,
    ),
    FailureType.UNMOTIVATED_EPIPHANY: (
        "scene_writer",
        "补认知变化过程（S1 认知变化 → S2 价值冲突 → 再行动）",
        Severity.MEDIUM,
    ),
    FailureType.GENERIC_CHARACTER: (
        "character_architect",
        "让职业/价值/关系真正参与行为设计（反事实 Test C/D/E 须改变行为）",
        Severity.MEDIUM,
    ),
    FailureType.CAUSAL_LEAP: (
        "causal_planner",
        "补中间节点（B、C）及必然性来源（角色价值或环境规则）",
        Severity.HIGH,
    ),
    FailureType.FORCED_TWIST: (
        "causal_planner",
        "反转改由人物选择/信息揭示驱动，补伏笔",
        Severity.HIGH,
    ),
    FailureType.THEME_EXPOSITION: (
        "scene_writer",
        "删说教句，主题留给读者从人物选择推导",
        Severity.MEDIUM,
    ),
    FailureType.EMOTIONAL_SHORTCUT_WARNING: (
        "scene_writer",
        "套路元素改为与人物价值/历史/行动真正相关（验证参与而非替代深度）",
        Severity.MEDIUM,
    ),
    FailureType.FORCED_DEATH: (
        "causal_planner",
        "死亡必须由因果必然性驱动（价值冲突/环境压力），删随机悲剧",
        Severity.HIGH,
    ),
    FailureType.TIMELINE_CONFLICT: (
        "world_architect",
        "修正时间线锚点与事件顺序（查 StoryState.timeline）",
        Severity.HIGH,
    ),
    FailureType.MEMORY_ERROR: (
        "state_validator",
        "人物记忆与 StoryState.facts 对齐（事实以状态为准）",
        Severity.HIGH,
    ),
    FailureType.KNOWLEDGE_LEAK: (
        "state_validator",
        "知识状态修正：谁在何时知道什么（knowledge_state 与 timeline 对齐）",
        Severity.HIGH,
    ),
    FailureType.STYLE_OVERRIDE: (
        "style_agent",
        "还原被修改的事实指纹；Style 层仅允许 FLEXIBLE 差异",
        Severity.HIGH,
    ),
    FailureType.FALSE_DILEMMA: (
        "value_architect",
        "两难必须来自真实价值冲突（权重差 <0.2）；否则删假两难",
        Severity.MEDIUM,
    ),
    FailureType.SYMBOL_OVERLOAD: (
        "style_agent",
        "意象削减并赋予意义演进；防象征过载",
        Severity.MEDIUM,
    ),
    FailureType.ADJECTIVE_STACKING: (
        "style_agent",
        "形容词改为具体行为/细节/证据支撑",
        Severity.MEDIUM,
    ),
    FailureType.DIALOGUE_HOMOGENEOUS: (
        "scene_writer",
        "对白按人物 Constitution（说话方式/决策规则）差异化",
        Severity.MEDIUM,
    ),
    FailureType.LOOP_LEAK: (
        "narrative_planner",
        "安排回收伏笔；或显式标记伏笔废弃",
        Severity.MEDIUM,
    ),
    FailureType.SWAPPABLE_CHARACTER: (
        "character_architect",
        "角色价值/职业/关系参与剧情：换人故事必须改变",
        Severity.MEDIUM,
    ),
}


def repair_strategy_for(failure_type: FailureType) -> list[RepairStrategy]:
    """failure_type → 修复策略（机器可读，供 Repair Agent 执行）。"""
    entry = _REPAIR_MAP.get(failure_type)
    if entry is None:
        return [RepairStrategy(stage="scene_writer", action="按 Diagnostic 定位局部修复")]
    stage, action, _sev = entry
    return [RepairStrategy(stage=stage, action=action)]


def make_diagnostic(
    *,
    metric: MetricName,
    score: float,
    threshold: float,
    failure_type: FailureType,
    chapter_no: int,
    evidence: list[DiagnosticEvidence],
    retry_used: int,
    retry_max: int = 2,
) -> DiagnosticReport:
    """组装 DiagnosticReport（status=REJECT；修复策略由映射表生成）。"""
    strategy = repair_strategy_for(failure_type)
    _stage, _action, severity = _REPAIR_MAP.get(
        failure_type, ("scene_writer", "", Severity.MEDIUM)
    )
    return DiagnosticReport(
        status=GateVerdict.REJECT,
        metric=metric,
        score=score,
        threshold=threshold,
        failure_type=failure_type,
        severity=severity,
        chapter_no=chapter_no,
        evidence=evidence,
        repair_strategy=strategy,
        retry_budget=RetryBudget(used=retry_used, max=retry_max),
    )


def gate_verdict(score: float, threshold: float) -> GateVerdict:
    """L0 硬门：score >= threshold → PASS，否则 REJECT（禁止加权掩盖）。"""
    return GateVerdict.PASS if score >= threshold else GateVerdict.REJECT
