"""创作智能数据模型（pydantic v2）。

分层对应 docs/creative-engine/：
- 03_CHARACTER_MODEL：CharacterConstitution（22 字段）+ CharacterState（S0-S4 状态机）
- 04_VALUE_MODEL：ValueHierarchy + MotivationTrace + FailureType 字典
- 05_STORY_STATE_MODEL：StoryState + StateDelta（Scene → State Transition）
- 06_QUALITY_GATE：DiagnosticReport / CreativeQualityReport

设计约束：
- 价值层级：权重 ∈ [0,1]、非空、顶部值唯一（禁止并列最高，保证"最重要的东西"可判定）
- core_values ⊆ value_hierarchy（核心价值观必须是层级顶端子集）
- 情绪触发器与核心价值分离（independent of value_hierarchy）
- StateDelta 的每条变更必须带 text_anchor（正文锚点，供 StateValidator 交叉验证）
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# ============================================================
# 枚举与常量
# ============================================================


class FailureType(StrEnum):
    """L0 失败类型字典（04 §4）。机器可读，Critic 输出必须从本表取值。"""

    CHARACTER_VALUE_HIERARCHY_COLLAPSE = "CHARACTER_VALUE_HIERARCHY_COLLAPSE"
    MOTIVATION_DOWNGRADE = "MOTIVATION_DOWNGRADE"
    EMOTIONAL_OVERRIDE = "EMOTIONAL_OVERRIDE"
    THEME_FORCED_ACTION = "THEME_FORCED_ACTION"
    PLOT_FORCED_ACTION = "PLOT_FORCED_ACTION"
    AUTHORIAL_FORCED_ACTION = "AUTHORIAL_FORCED_ACTION"
    COINCIDENCE_DEPENDENCY = "COINCIDENCE_DEPENDENCY"
    MISSING_MOTIVATION = "MISSING_MOTIVATION"
    VALUE_FLIP_WITHOUT_PROCESS = "VALUE_FLIP_WITHOUT_PROCESS"
    UNMOTIVATED_EPIPHANY = "UNMOTIVATED_EPIPHANY"
    GENERIC_CHARACTER = "GENERIC_CHARACTER"
    CAUSAL_LEAP = "CAUSAL_LEAP"
    FORCED_TWIST = "FORCED_TWIST"
    THEME_EXPOSITION = "THEME_EXPOSITION"
    EMOTIONAL_SHORTCUT_WARNING = "EMOTIONAL_SHORTCUT_WARNING"
    FORCED_DEATH = "FORCED_DEATH"
    TIMELINE_CONFLICT = "TIMELINE_CONFLICT"
    MEMORY_ERROR = "MEMORY_ERROR"
    KNOWLEDGE_LEAK = "KNOWLEDGE_LEAK"
    STYLE_OVERRIDE = "STYLE_OVERRIDE"
    FALSE_DILEMMA = "FALSE_DILEMMA"
    SYMBOL_OVERLOAD = "SYMBOL_OVERLOAD"
    ADJECTIVE_STACKING = "ADJECTIVE_STACKING"
    DIALOGUE_HOMOGENEOUS = "DIALOGUE_HOMOGENEOUS"
    LOOP_LEAK = "LOOP_LEAK"
    SWAPPABLE_CHARACTER = "SWAPPABLE_CHARACTER"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CharacterStage(StrEnum):
    """状态机（03 §6）：S0 稳态 → S1 认知变化 → S2 价值冲突 → S3 行为 → S4 成长。"""

    S0_STABLE = "S0"
    S1_COGNITIVE_SHIFT = "S1"
    S2_VALUE_CONFLICT = "S2"
    S3_ACTION = "S3"
    S4_GROWTH = "S4"


class FactTier(StrEnum):
    """不可变事实分级（05 §2）。"""

    IMMUTABLE = "IMMUTABLE"
    IMPORTANT = "IMPORTANT"
    FLEXIBLE = "FLEXIBLE"


class MetricName(StrEnum):
    CVI = "CVI"
    CAI = "CAI"
    CCI = "CCI"
    WCI = "WCI"


class GateVerdict(StrEnum):
    PASS = "PASS"
    REJECT = "REJECT"
    REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


# 情绪捷径词库（07 §5.1）——确定性检查用，与 schema 无关但就近登记
EMOTIONAL_SHORTCUT_LEXICON: tuple[str, ...] = (
    "雨", "旧照片", "旧信", "遗物", "死亡", "故乡", "十年", "孤独", "等待",
    "老屋", "桥", "船", "黄河", "唢呐", "灯", "月", "背影", "墓碑",
    "未寄出的信", "台阶", "炊烟", "老槐树", "手绢", "车站", "老街",
    "黄昏", "麦田", "雪地", "油纸伞", "青石板", "旗袍", "离愁",
)


# ============================================================
# 人物模型（03）
# ============================================================


class RelationshipLink(BaseModel):
    """关系对象。value_link 必填：关系必须挂载到某条价值上（03 §2 关键约束）。"""

    name: str = Field(min_length=1, max_length=100)
    relation: str = Field(default="", max_length=100)
    emotional_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    value_link: str = Field(
        min_length=1, max_length=100,
        description="这段关系挂载在 value_hierarchy 的哪条价值上（必填，防工具人关系）",
    )


class DecisionRule(BaseModel):
    """决策规则（03 §5）：if-then 式，从价值层级推导。"""

    condition: str = Field(min_length=1, max_length=500)
    action: str = Field(min_length=1, max_length=500)
    rationale: str = Field(default="", max_length=500)


class CharacterConstitution(BaseModel):
    """Character Constitution（03 §2，22 字段）。静态设定，故事中不直接改（IMMUTABLE 级）。"""

    identity: str = Field(default="", max_length=2000)
    worldview: str = Field(default="", max_length=2000)
    beliefs: list[str] = Field(default_factory=list, max_length=30)
    core_values: list[str] = Field(default_factory=list, max_length=10)
    value_hierarchy: dict[str, float] = Field(default_factory=dict)
    mission: str = Field(default="", max_length=2000)
    goals: list[str] = Field(default_factory=list, max_length=20)
    desires: list[str] = Field(default_factory=list, max_length=20)
    fears: list[str] = Field(default_factory=list, max_length=20)
    needs: list[str] = Field(default_factory=list, max_length=20)
    relationships: list[RelationshipLink] = Field(default_factory=list, max_length=50)
    history: list[str] = Field(default_factory=list, max_length=50)
    skills: list[str] = Field(default_factory=list, max_length=50)
    weaknesses: list[str] = Field(default_factory=list, max_length=20)
    contradictions: list[str] = Field(default_factory=list, max_length=20)
    boundaries: list[str] = Field(default_factory=list, max_length=20)
    moral_limits: list[str] = Field(default_factory=list, max_length=20)
    decision_rules: list[DecisionRule] = Field(default_factory=list, max_length=50)
    emotional_triggers: list[str] = Field(default_factory=list, max_length=30)
    character_arc: str = Field(default="", max_length=3000)

    @field_validator("value_hierarchy")
    @classmethod
    def _weights_in_range(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            raise ValueError("value_hierarchy 不能为空：必须明确人物'最重要的东西是什么'")
        for key, w in v.items():
            if not (0.0 <= float(w) <= 1.0):
                raise ValueError(f"价值权重 {key}={w} 必须 ∈ [0,1]")
        return {k: float(w) for k, w in v.items()}

    @field_validator("core_values")
    @classmethod
    def _core_values_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("core_values 不能为空：至少 1 条核心价值观")
        return v

    @model_validator(mode="after")
    def _integrity(self) -> CharacterConstitution:
        # 1) core_values ⊆ value_hierarchy（价值观必须是层级中的）
        vh = set(self.value_hierarchy.keys())
        missing = [c for c in self.core_values if c not in vh]
        if missing:
            raise ValueError(
                f"core_values 必须在 value_hierarchy 中，缺失: {missing}"
            )
        # 2) 顶部值唯一（禁止并列最高——"最重要的东西"必须可判定）
        if vh:
            top = max(self.value_hierarchy.values())
            tops = [k for k, w in self.value_hierarchy.items() if abs(float(w) - top) < 1e-9]
            if len(tops) > 1:
                raise ValueError(f"value_hierarchy 顶部值必须唯一，当前并列: {tops}")
        # 3) 情绪触发器与核心价值分离（04 §4：禁止自动互相推导）
        overlap = set(self.emotional_triggers) & set(self.core_values)
        if overlap:
            raise ValueError(
                f"情绪触发器与核心价值观重叠（必须分离）: {overlap}"
            )
        return self

    def top_value(self) -> str | None:
        """最高价值（顶层动机判定的依据）。"""
        if not self.value_hierarchy:
            return None
        return max(self.value_hierarchy, key=lambda k: self.value_hierarchy[k])

    def weight(self, value: str) -> float:
        return float(self.value_hierarchy.get(value, 0.0))


class CharacterState(BaseModel):
    """动态人物状态（03 §6/§7）。随章节由 StateDelta 提案更新。"""

    stage: CharacterStage = CharacterStage.S0_STABLE
    stage_since: str = Field(default="", max_length=50)  # 进入该阶段的章节标识
    value_weights: dict[str, float] = Field(default_factory=dict)  # 当前价值权重（弧线追踪）
    active_conflict: str = Field(default="", max_length=1000)
    pending_decision: str | None = Field(default=None, max_length=1000)
    knowledge: list[str] = Field(default_factory=list, max_length=100)  # 角色知道什么
    relationship_deltas: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    emotion: dict[str, Any] = Field(
        default_factory=lambda: {"primary": "", "intensity": 0.0}
    )

    @field_validator("value_weights")
    @classmethod
    def _w_in_range(cls, v: dict[str, float]) -> dict[str, float]:
        for k, w in v.items():
            if not (0.0 <= float(w) <= 1.0):
                raise ValueError(f"value_weights {k}={w} 必须 ∈ [0,1]")
        return {k: float(w) for k, w in v.items()}


# ============================================================
# 动机链（04 §2）
# ============================================================


class MotivationTrace(BaseModel):
    """重大行为的动机链：Worldview→Value→Mission→Goal→Situation→Conflict→Decision→Action→Consequence。

    缺失环节 = broken_at（04 §2.3：`CHARACTER_VALUE_HIERARCHY_COLLAPSE` 等诊断的证据来源）。
    """

    character: str = Field(default="", max_length=100)
    action: str = Field(default="", max_length=1000)
    worldview: str = Field(default="", max_length=1000)
    value: str = Field(default="", max_length=200)
    mission: str = Field(default="", max_length=1000)
    goal: str = Field(default="", max_length=1000)
    situation: str = Field(default="", max_length=1000)
    conflict: str = Field(default="", max_length=1000)
    decision: str = Field(default="", max_length=1000)
    consequence: str = Field(default="", max_length=1000)
    broken_at: str = Field(default="", max_length=200)  # 空 = 链完整

    def is_complete(self) -> bool:
        return not self.broken_at


# ============================================================
# Story State（05）
# ============================================================


class WorldRule(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    tier: FactTier = FactTier.IMMUTABLE


class LocationState(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(default="", max_length=200)
    status: str = Field(default="", max_length=500)
    occupants: list[str] = Field(default_factory=list, max_length=50)


class TimelineEvent(BaseModel):
    at: str = Field(default="", max_length=200)  # 时间锚点（第几章/日期/时刻）
    chapter: int = Field(default=0, ge=0)
    event: str = Field(default="", max_length=1000)
    caused_by: str = Field(default="", max_length=200)


class CausalNode(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    type: str = Field(default="event", max_length=50)  # event / decision / state_change
    desc: str = Field(default="", max_length=1000)
    chapter: int = Field(default=0, ge=0)


class CausalEdge(BaseModel):
    from_node: str = Field(min_length=1, max_length=100)
    to_node: str = Field(min_length=1, max_length=100)
    kind: str = Field(default="causes", max_length=50)  # causes / enables / forces
    necessity: str = Field(default="", max_length=200)  # role | environment | chance（05 §1）


class OpenLoop(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    planted_chapter: int = Field(ge=1)
    desc: str = Field(default="", max_length=1000)
    expected_payoff: str = Field(default="", max_length=1000)


class ResolvedLoop(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    resolved_chapter: int = Field(ge=1)
    how: str = Field(default="", max_length=1000)


class KnowledgeEntry(BaseModel):
    character: str = Field(min_length=1, max_length=100)
    knows: str = Field(default="", max_length=1000)
    since_chapter: int = Field(default=0, ge=0)


class GoalState(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    goal: str = Field(default="", max_length=1000)
    status: str = Field(default="active", max_length=50)  # active / done / failed / abandoned


class RelationshipState(BaseModel):
    a: str = Field(min_length=1, max_length=100)
    b: str = Field(min_length=1, max_length=100)
    trust: float = Field(default=0.5, ge=0.0, le=1.0)
    closeness: float = Field(default=0.5, ge=0.0, le=1.0)
    note: str = Field(default="", max_length=1000)


class SymbolEntry(BaseModel):
    symbol: str = Field(min_length=1, max_length=100)
    first_use: str = Field(default="", max_length=50)
    instances: list[str] = Field(default_factory=list, max_length=50)
    meaning: str = Field(default="", max_length=1000)


class ThemeProposition(BaseModel):
    claim: str = Field(default="", max_length=1000)
    characters_voicing: list[str] = Field(default_factory=list, max_length=20)
    chapter: int = Field(default=0, ge=0)


class ThemeState(BaseModel):
    propositions: list[ThemeProposition] = Field(default_factory=list, max_length=50)
    emergence_score: float = Field(default=0.0, ge=0.0, le=1.0)  # 主题涌现度（人物驱动 vs 注入）


class WorldState(BaseModel):
    rules: list[WorldRule] = Field(default_factory=list, max_length=100)
    locations: list[LocationState] = Field(default_factory=list, max_length=200)
    institutions: list[str] = Field(default_factory=list, max_length=100)
    facts: list[str] = Field(default_factory=list, max_length=1000)


class Timeline(BaseModel):
    anchors: list[str] = Field(default_factory=list, max_length=100)  # IMMUTABLE 关键节点
    events: list[TimelineEvent] = Field(default_factory=list, max_length=2000)


class CausalGraph(BaseModel):
    nodes: list[CausalNode] = Field(default_factory=list, max_length=1000)
    edges: list[CausalEdge] = Field(default_factory=list, max_length=2000)


class StoryState(BaseModel):
    """故事状态（05 §1）。每生成一个 Scene → State Transition（version+1）。"""

    version: int = Field(default=0, ge=0)
    project_id: str = Field(default="", max_length=36)
    world_state: WorldState = Field(default_factory=WorldState)
    timeline: Timeline = Field(default_factory=Timeline)
    character_states: dict[str, CharacterState] = Field(default_factory=dict)
    relationship_states: list[RelationshipState] = Field(default_factory=list, max_length=500)
    value_states: dict[str, dict[str, float]] = Field(default_factory=dict)
    goal_states: list[GoalState] = Field(default_factory=list, max_length=200)
    knowledge_state: list[KnowledgeEntry] = Field(default_factory=list, max_length=500)
    open_loops: list[OpenLoop] = Field(default_factory=list, max_length=200)
    resolved_loops: list[ResolvedLoop] = Field(default_factory=list, max_length=500)
    causal_graph: CausalGraph = Field(default_factory=CausalGraph)
    symbol_state: list[SymbolEntry] = Field(default_factory=list, max_length=200)
    theme_state: ThemeState = Field(default_factory=ThemeState)


class StateDelta(BaseModel):
    """Scene → State Transition 的变更提案（05 §1.1）。

    每条变更必须能在正文中找到锚点（text_anchors），由 StateValidator 交叉验证。
    """

    facts_added: list[str] = Field(default_factory=list, max_length=100)
    timeline_events: list[TimelineEvent] = Field(default_factory=list, max_length=50)
    character_deltas: dict[str, CharacterState] = Field(default_factory=dict, max_length=50)
    relationship_deltas: list[RelationshipState] = Field(default_factory=list, max_length=50)
    goal_updates: list[GoalState] = Field(default_factory=list, max_length=50)
    knowledge_updates: list[KnowledgeEntry] = Field(default_factory=list, max_length=100)
    loops_opened: list[OpenLoop] = Field(default_factory=list, max_length=50)
    loops_resolved: list[ResolvedLoop] = Field(default_factory=list, max_length=50)
    causal_edges: list[CausalEdge] = Field(default_factory=list, max_length=100)
    symbol_updates: list[SymbolEntry] = Field(default_factory=list, max_length=50)
    theme_evidence: list[ThemeProposition] = Field(default_factory=list, max_length=50)
    text_anchors: dict[str, str] = Field(
        default_factory=dict, max_length=500,
        description="变更声明 → 正文锚点（段/句），供 StateValidator 做 text-anchor 校验",
    )


# ============================================================
# 诊断与质量报告（06）
# ============================================================


class DiagnosticEvidence(BaseModel):
    text: str = Field(default="", max_length=2000)
    text_anchor: str = Field(default="", max_length=200)
    reason: str = Field(default="", max_length=1000)


class RepairStrategy(BaseModel):
    stage: str = Field(default="", max_length=100)  # 回退阶段（value_architect 等）
    action: str = Field(default="", max_length=2000)


class CounterfactualResult(BaseModel):
    """反事实人物测试（07 §6）：A-E。"""

    drop_emotion_object: bool | None = None  # A：删情感对象，行为仍成立？
    drop_theme: bool | None = None           # B：删主题，行为仍成立？
    change_profession: bool | None = None    # C：换职业，行为改变？
    change_value_hierarchy: bool | None = None  # D：换价值层级，行为改变？
    substitute_relation: bool | None = None  # E：换关系对象，故事改变？


class RetryBudget(BaseModel):
    used: int = Field(default=0, ge=0)
    max: int = Field(default=2, ge=1)


class DiagnosticReport(BaseModel):
    """L0 失败诊断（06 §4）。机器可读：failure_type 从 FailureType 取，不得自由发挥。"""

    status: GateVerdict = GateVerdict.REJECT
    metric: MetricName
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    failure_type: FailureType
    severity: Severity = Severity.HIGH
    chapter_no: int = Field(default=0, ge=0)
    evidence: list[DiagnosticEvidence] = Field(default_factory=list, max_length=50)
    character_value: dict[str, Any] = Field(default_factory=dict)
    action: dict[str, Any] = Field(default_factory=dict)
    motivation_trace: MotivationTrace | None = None
    violations: list[dict[str, str]] = Field(default_factory=list, max_length=50)
    counterfactual: CounterfactualResult | None = None
    repair_strategy: list[RepairStrategy] = Field(default_factory=list, max_length=20)
    retry_budget: RetryBudget = Field(default_factory=RetryBudget)


class QualityIssue(BaseModel):
    level: str = Field(default="minor", max_length=20)  # critical / major / minor
    text: str = Field(default="", max_length=1000)


class RepairHistoryEntry(BaseModel):
    round: int = Field(default=1, ge=1)
    issue: str = Field(default="", max_length=1000)
    fixed: bool = True


class CreativeQualityReport(BaseModel):
    """Creative Quality Report（06 §5）：每次生成完成后的质量报告。"""

    character_value_integrity: float = Field(ge=0.0, le=1.0)
    character_agency: float = Field(ge=0.0, le=1.0)
    causal_integrity: float = Field(ge=0.0, le=1.0)
    world_consistency: float = Field(ge=0.0, le=1.0)
    semantic_diversity: float = Field(ge=0.0, le=1.0)
    narrative_diversity: float = Field(ge=0.0, le=1.0)
    emotional_authenticity: float = Field(ge=0.0, le=1.0)
    theme_emergence: float = Field(ge=0.0, le=1.0)
    cliche_risk: float = Field(ge=0.0, le=1.0)
    style_risk: float = Field(ge=0.0, le=1.0)
    critical_issues: list[QualityIssue] = Field(default_factory=list, max_length=20)
    major_issues: list[QualityIssue] = Field(default_factory=list, max_length=50)
    minor_issues: list[QualityIssue] = Field(default_factory=list, max_length=100)
    repair_history: list[RepairHistoryEntry] = Field(default_factory=list, max_length=10)
    final_status: GateVerdict = GateVerdict.PASS
    generated_at: datetime | None = None
