"""创作智能内核 P0 测试：schema 校验 / StateValidator / 情绪捷径检测。

对应 docs/creative-engine/09 §4 单元测试 11/12/13 的确定性部分 + schema 约束。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from app.core.database import Base
from app.creative.cliche_detector import detect_shortcuts
from app.creative.schemas import (
    CausalEdge,
    CharacterConstitution,
    CharacterStage,
    CharacterState,
    DiagnosticReport,
    FailureType,
    GateVerdict,
    MetricName,
    OpenLoop,
    ResolvedLoop,
    Severity,
    StateDelta,
    StoryState,
    TimelineEvent,
)
from app.creative.state_validator import (
    ValidationResultCode,
    apply_delta,
    validate_state_delta,
)
from pydantic import ValidationError

from tests.conftest import TestingSessionLocal, _test_engine

# ============================================================
# CharacterConstitution（03 §2 + 04 §1 约束）
# ============================================================

_BASE_CONSTITUTION = {
    "identity": "陈工，守桥人",
    "worldview": "工程质量即生命",
    "beliefs": ["桥是要用一辈子的"],
    "core_values": ["公共安全", "责任"],
    "value_hierarchy": {"公共安全": 1.0, "责任": 0.95, "家庭": 0.75},
    "mission": "守住这座桥",
    "goals": ["完成 3 号墩复检"],
    "desires": [],
    "fears": ["桥出事"],
    "needs": ["被需要"],
    "relationships": [{"name": "妻子", "relation": "配偶", "emotional_weight": 0.9,
                       "value_link": "家庭"}],
    "history": ["守桥 30 年"],
    "skills": ["桥梁病害检测"],
    "weaknesses": ["固执"],
    "contradictions": ["想退休又放不下桥"],
    "boundaries": ["不隐瞒隐患"],
    "moral_limits": ["绝不牺牲他人安全"],
    "decision_rules": [{"condition": "公共安全受威胁", "action": "立即采取措施",
                        "rationale": "公共安全=1.0 最高"}],
    "emotional_triggers": ["提到那座垮掉的桥"],
    "character_arc": "从守桥到育人",
}


def test_constitution_valid() -> None:
    c = CharacterConstitution(**dict(_BASE_CONSTITUTION))
    assert c.top_value() == "公共安全"
    assert c.weight("责任") == 0.95


def test_constitution_value_hierarchy_nonempty() -> None:
    d = dict(_BASE_CONSTITUTION)
    d["value_hierarchy"] = {}
    with pytest.raises(ValidationError, match="不能为空"):
        CharacterConstitution(**d)


def test_constitution_weight_out_of_range() -> None:
    d = dict(_BASE_CONSTITUTION)
    d["value_hierarchy"] = {"公共安全": 1.5, "责任": 0.95, "家庭": 0.75}
    with pytest.raises(ValidationError, match="∈ \\[0,1\\]"):
        CharacterConstitution(**d)


def test_constitution_top_value_unique() -> None:
    d = dict(_BASE_CONSTITUTION)
    d["value_hierarchy"] = {"公共安全": 1.0, "责任": 1.0, "家庭": 0.75}
    with pytest.raises(ValidationError, match="顶部值必须唯一"):
        CharacterConstitution(**d)


def test_constitution_core_values_subset() -> None:
    d = dict(_BASE_CONSTITUTION)
    d["core_values"] = ["名誉"]  # 不在 value_hierarchy
    with pytest.raises(ValidationError, match="必须在 value_hierarchy"):
        CharacterConstitution(**d)


def test_constitution_emotion_separated_from_value() -> None:
    d = dict(_BASE_CONSTITUTION)
    d["emotional_triggers"] = ["公共安全"]  # 与核心价值重叠
    with pytest.raises(ValidationError, match="分离"):
        CharacterConstitution(**d)


def test_constitution_relationship_needs_value_link() -> None:
    d = dict(_BASE_CONSTITUTION)
    d["relationships"] = [{"name": "妻子", "relation": "配偶", "emotional_weight": 0.9}]
    with pytest.raises(ValidationError, match="value_link"):
        CharacterConstitution(**d)


# ============================================================
# StateValidator（05 §3.3）
# ============================================================


def _empty_state() -> StoryState:
    return StoryState(project_id="p1")


def test_validator_accepts_well_formed_delta() -> None:
    cur = _empty_state()
    delta = StateDelta(
        facts_added=["复检报告异常"],
        timeline_events=[TimelineEvent(at="第 1 章", chapter=1, event="陈工缺席剪彩")],
        character_deltas={
            "陈工": CharacterState(
                stage=CharacterStage.S1_COGNITIVE_SHIFT,
                value_weights={"公共安全": 1.0},
            )
        },
        loops_opened=[OpenLoop(id="l1", planted_chapter=1, desc="3 号墩隐患")],
        causal_edges=[CausalEdge(from_node="复检报告异常", to_node="陈工缺席剪彩",
                                 necessity="role")],
        text_anchors={
            "陈工缺席剪彩": "ch1/para-3",
            "l1": "ch1/para-3",
            "复检报告异常->陈工缺席剪彩": "ch1/para-2",
        },
    )
    res = validate_state_delta(cur, delta)
    assert res.code is ValidationResultCode.ACCEPT, res.reasons


def test_validator_rejects_stage_jump() -> None:
    """禁止 S0 → S3/S4 跳跃（无过程顿悟）。"""
    cur = _empty_state()
    delta = StateDelta(
        character_deltas={
            "陈工": CharacterState(stage=CharacterStage.S4_GROWTH),
        },
        text_anchors={},
    )
    res = validate_state_delta(cur, delta, require_anchors=False)
    assert res.code is ValidationResultCode.REJECT
    assert any("状态机非法迁移" in r for r in res.reasons)


def test_validator_rejects_missing_causal_node() -> None:
    cur = _empty_state()
    delta = StateDelta(
        causal_edges=[CausalEdge(from_node="不存在的节点", to_node="另一个不存在",
                                 necessity="chance")],
        text_anchors={},
    )
    res = validate_state_delta(cur, delta, require_anchors=False)
    assert res.code is ValidationResultCode.REJECT
    assert any("from 节点不存在" in r for r in res.reasons)


def test_validator_rejects_unresolvable_loop() -> None:
    cur = _empty_state()
    delta = StateDelta(
        loops_resolved=[ResolvedLoop(id="ghost", resolved_chapter=2, how="回收")],
        text_anchors={},
    )
    res = validate_state_delta(cur, delta, require_anchors=False)
    assert res.code is ValidationResultCode.REJECT
    assert any("resolved loop 不存在" in r for r in res.reasons)


def test_validator_rejects_missing_anchor() -> None:
    cur = _empty_state()
    delta = StateDelta(
        facts_added=["新事实"],
        text_anchors={},  # 没有任何锚点
    )
    res = validate_state_delta(cur, delta, require_anchors=True)
    assert res.code is ValidationResultCode.REJECT
    assert any("text-anchor 缺失" in r for r in res.reasons)


def test_apply_delta_advances_state() -> None:
    cur = _empty_state()
    delta = StateDelta(
        facts_added=["桥通了"],
        timeline_events=[TimelineEvent(at="第 1 章", chapter=1, event="通车")],
        loops_opened=[OpenLoop(id="l1", planted_chapter=1, desc="隐患")],
        character_deltas={
            "陈工": CharacterState(stage=CharacterStage.S1_COGNITIVE_SHIFT,
                                   value_weights={"公共安全": 1.0}),
        },
        causal_edges=[CausalEdge(from_node="通车", to_node="陈工缺席", necessity="role")],
        text_anchors={},
    )
    nxt = apply_delta(cur, delta)
    assert nxt.version == 1
    assert "桥通了" in nxt.world_state.facts
    assert len(nxt.timeline.events) == 1
    assert nxt.open_loops[0].id == "l1"
    assert nxt.character_states["陈工"].stage is CharacterStage.S1_COGNITIVE_SHIFT
    # 隐式因果节点
    assert any(n.id == "通车" for n in nxt.causal_graph.nodes)


def test_apply_delta_resolves_loop() -> None:
    cur = _empty_state()
    cur.open_loops.append(OpenLoop(id="l1", planted_chapter=1, desc="隐患"))
    delta = StateDelta(
        loops_resolved=[ResolvedLoop(id="l1", resolved_chapter=3, how="复检确认安全")],
        text_anchors={},
    )
    nxt = apply_delta(cur, delta)
    assert nxt.open_loops == []
    assert nxt.resolved_loops[0].id == "l1"


# ============================================================
# 情绪捷径检测（07 §5）
# ============================================================


def test_shortcut_clean_text() -> None:
    r = detect_shortcuts("他检查完伸缩缝，在报告上签了字。")
    assert r.hits == []
    assert r.level == 0


def test_shortcut_detects_rain() -> None:
    r = detect_shortcuts("雨下了整夜，他看着旧照片。")
    assert {h.term for h in r.hits} >= {"雨", "旧照片"}


def test_shortcut_cluster_when_no_depth() -> None:
    """套路组合拳 + 人物维度缺席 → level 3（SHORTCUT_AS_DEPTH 启发式）。"""
    text = "雨落在老屋的台阶上，他握着旧照片等了一个十年，月下的背影是故乡。"
    r = detect_shortcuts(text)
    assert r.level == 3
    assert r.shortcut_as_depth is True


def test_shortcut_render_only_when_depth_present() -> None:
    """人物维度在场（价值/职业/决策词）→ 不判替代深度，只给 RENDER_ONLY。"""
    text = "雨下着，他在桥墩做完复检，在责任书上签了字。"
    r = detect_shortcuts(text)
    assert r.depth_signal_count >= 2
    assert r.level == 1
    assert r.render_only is True


def test_shortcut_cluster_level() -> None:
    text = (
        "雨落在老屋，旧照片放在桥边，船停在黄河岸，唢呐声穿过老街，"
        "他在责任书上签了字，工程师的复检报告写完了。"
    )
    r = detect_shortcuts(text)
    assert r.cluster is True
    assert r.level == 2


# ============================================================
# 语义多样性（07 §7）
# ============================================================


def test_diversity_cross_domain_passes() -> None:
    from app.creative.semantic_diversity import (
        EXAMPLE_CROSS_DOMAIN,
        diversity_score,
    )

    v = diversity_score(EXAMPLE_CROSS_DOMAIN)
    assert v.passed is True
    assert v.first_association is False


def test_diversity_first_association_warns() -> None:
    from app.creative.semantic_diversity import (
        EXAMPLE_FIRST_ASSOCIATION,
        diversity_score,
    )

    v = diversity_score(EXAMPLE_FIRST_ASSOCIATION)
    assert v.passed is False
    assert v.first_association is True
    assert v.similar_pairs  # 存在高相似方向对


def test_diversity_insufficient_directions() -> None:
    from app.creative.semantic_diversity import SemanticDirection, diversity_score

    v = diversity_score([SemanticDirection("a", ["x"])])
    assert v.passed is False
    assert "不足" in v.detail


# ============================================================
# Style Firewall（07 §8）
# ============================================================


def test_style_polish_keeps_facts() -> None:
    from app.creative.style_firewall import check_style_delta

    original = "他检查完伸缩缝，在报告上签了字。"
    variant = "他缓缓检查完伸缩缝，在验收报告上慎重地签了字。"
    v = check_style_delta(original, variant, terms=("陈工", "伸缩缝"))
    assert v.accepted is True, v.detail
    assert v.removed_terms == []


def test_style_removes_number_rejected() -> None:
    from app.creative.style_firewall import check_style_delta

    original = "3 号墩的复检数据出来了。"
    variant = "复检数据出来了。"
    v = check_style_delta(original, variant)
    assert v.accepted is False
    assert "3" in v.removed_numbers


def test_style_removes_terms_rejected() -> None:
    from app.creative.style_firewall import check_style_delta

    original = "陈工在桥墩做了复检。"
    variant = "他在桥墩做了复检。"
    v = check_style_delta(original, variant, terms=("陈工",))
    assert v.accepted is False
    assert "陈工" in v.removed_terms


def test_style_injects_repeated_unknown_terms() -> None:
    """变体重复注入新词（新叙事要素）→ REJECT（疑似新事实）。"""
    from app.creative.style_firewall import check_style_delta

    original = "他检查完伸缩缝，在报告上签了字。"
    variant = "他检查完伸缩缝，看到雪莲花的影子，想起雪莲花开在山顶的事，在报告上签了字。"
    v = check_style_delta(original, variant)
    assert v.accepted is False
    assert any("雪莲花" in t for t in v.added_unknown_terms)


# ============================================================
# 状态一致性确定性检查（05 §7）
# ============================================================


def test_timeline_consistency_ok_and_conflict() -> None:
    from app.creative.schemas import StoryState, Timeline, TimelineEvent
    from app.creative.state_checks import check_timeline_consistency

    ok = StoryState(
        timeline=Timeline(events=[TimelineEvent(at="第 1 章", chapter=1, event="通车"),
                                  TimelineEvent(at="第 2 章", chapter=2, event="复检")])
    )
    assert check_timeline_consistency(ok).ok is True

    bad = StoryState(
        timeline=Timeline(events=[TimelineEvent(at="第 2 章", chapter=2, event="复检"),
                                  TimelineEvent(at="第 1 章", chapter=1, event="通车")])
    )
    r = check_timeline_consistency(bad)
    assert r.ok is False
    assert any("时间线矛盾" in p for p in r.problems)


def test_knowledge_leak_detected() -> None:
    from app.creative.schemas import (
        KnowledgeEntry,
        StoryState,
        Timeline,
        TimelineEvent,
    )
    from app.creative.state_checks import check_knowledge_leak

    state = StoryState(
        timeline=Timeline(events=[TimelineEvent(at="第 3 章", chapter=3, event="3号墩隐患")]),
        knowledge_state=[KnowledgeEntry(character="陈工", knows="3号墩隐患", since_chapter=1)],
    )
    r = check_knowledge_leak(state)
    assert r.ok is False
    assert any("知识泄漏" in p for p in r.problems)


def test_loop_leak_detected() -> None:
    from app.creative.schemas import OpenLoop, StoryState, Timeline, TimelineEvent
    from app.creative.state_checks import check_loop_leak

    state = StoryState(
        timeline=Timeline(events=[TimelineEvent(at="第 15 章", chapter=15, event="x")]),
        open_loops=[OpenLoop(id="l1", planted_chapter=1, desc="旧伏笔")],
    )
    r = check_loop_leak(state, max_unchanged_chapters=10)
    assert r.ok is False
    assert any("LOOP_LEAK" in p for p in r.problems)


# ============================================================
# 持久化层（store）
# ============================================================


@pytest_asyncio.fixture
async def db_session():
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        yield session
    # teardown：清空本文件测试写入的数据（防跨文件污染共享内存库：
    # creative 测试创建 u1 项目/角色会污染 test_story_forge 的断言）
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_constitution_roundtrip(db_session) -> None:
    from app.creative.store import get_constitution, save_constitution
    from app.models.story_character import StoryCharacter

    db = db_session
    db.add(StoryCharacter(
        id="c1", project_id="p1", user_id="u1", name="陈工", role="protagonist"
    ))
    await db.commit()

    c = CharacterConstitution(**dict(_BASE_CONSTITUTION))
    assert await save_constitution(db, "c1", c) is True
    await db.commit()

    got = await get_constitution(db, "c1")
    assert got is not None
    assert got.top_value() == "公共安全"
    assert got.decision_rules[0].action == "立即采取措施"


async def test_constitution_missing_returns_none(db_session) -> None:
    from app.creative.store import get_constitution

    got = await get_constitution(db_session, "ghost-id")
    assert got is None


async def test_story_state_roundtrip(db_session) -> None:
    from app.creative.schemas import OpenLoop, StoryState
    from app.creative.store import (
        get_story_state,
        save_story_state,
        snapshot_story_state,
    )

    db = db_session
    state = StoryState(project_id="p1")
    state.open_loops.append(OpenLoop(id="l1", planted_chapter=1, desc="隐患"))
    await save_story_state(db, "p1", "u1", state, chapter_no=1)
    await snapshot_story_state(db, "p1", "u1", state, chapter_no=1)
    await db.commit()

    got = await get_story_state(db, "p1", "u1")
    assert got is not None
    assert got.open_loops[0].id == "l1"
    assert got.project_id == "p1"


async def test_story_state_empty_returns_none(db_session) -> None:
    from app.creative.store import get_story_state

    assert await get_story_state(db_session, "nope", "u1") is None


def test_constitution_bible_block() -> None:
    from app.creative.store import constitution_to_bible_block

    c = CharacterConstitution(**dict(_BASE_CONSTITUTION))
    block = constitution_to_bible_block(c, "陈工")
    assert "价值层级" in block
    assert "公共安全(1.00)" in block
    assert "决策规则" in block
    assert "情绪触发器" in block


# ============================================================
# Diagnostic 生成器（06 §4 + 08 §3）
# ============================================================


def test_repair_strategy_mapping() -> None:
    from app.creative.diagnostic import repair_strategy_for

    s = repair_strategy_for(FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE)
    assert s, "应有修复策略"
    assert s[0].stage == "value_architect"
    assert "情绪触发器" in s[0].action

    s2 = repair_strategy_for(FailureType.CAUSAL_LEAP)
    assert s2[0].stage == "causal_planner"


def test_make_diagnostic() -> None:
    from app.creative.diagnostic import make_diagnostic
    from app.creative.schemas import DiagnosticEvidence

    d = make_diagnostic(
        metric=MetricName.CVI,
        score=0.42,
        threshold=0.85,
        failure_type=FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE,
        chapter_no=7,
        evidence=[DiagnosticEvidence(text="x", text_anchor="ch7/para-1", reason="y")],
        retry_used=1,
        retry_max=2,
    )
    assert d.status is GateVerdict.REJECT
    assert d.severity is Severity.CRITICAL
    assert d.retry_budget.used == 1
    assert d.retry_budget.max == 2
    assert d.repair_strategy[0].stage == "value_architect"


def test_gate_verdict_no_weighted_cover() -> None:
    from app.creative.diagnostic import gate_verdict

    assert gate_verdict(0.84, 0.85) is GateVerdict.REJECT  # 差 0.01 也不行
    assert gate_verdict(0.85, 0.85) is GateVerdict.PASS


# ============================================================
# CVI 确定性预检（04 §3 前置层 + REGRESSION_CASE_001）
# ============================================================


def test_cvi_precheck_bridge_scenario_a_collapse() -> None:
    """桥的名字 · 典型错误：行为只由亡妻驱动 → CHARACTER_VALUE_HIERARCHY_COLLAPSE。"""
    from app.creative.critics.cvi_precheck import assess_behavior_motivation

    c = CharacterConstitution(**dict(_BASE_CONSTITUTION))
    pre = assess_behavior_motivation("通车那天他没去剪彩，因为想起亡妻。", c)
    assert pre.ok is False
    assert pre.failure_type is FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE
    assert pre.emotion_signals  # 情感信号在场
    assert not pre.value_signals  # 价值信号缺席


def test_cvi_precheck_bridge_scenario_b_value_driven() -> None:
    """桥的名字 · 正确方向：职业价值驱动行为，妻子进入情感层 → OK。"""
    from app.creative.critics.cvi_precheck import assess_behavior_motivation

    c = CharacterConstitution(**dict(_BASE_CONSTITUTION))
    pre = assess_behavior_motivation(
        "通车那天他没去剪彩。剪彩前夜，3 号墩的复检数据出来了，"
        "他带着报告去了桥墩现场。走到桥中央时，他才想起妻子生前说过的话。",
        c,
    )
    assert pre.ok is True
    assert pre.value_signals  # 复检/报告 等职业价值信号在场


def test_cvi_precheck_missing_motivation() -> None:
    from app.creative.critics.cvi_precheck import assess_behavior_motivation

    c = CharacterConstitution(**dict(_BASE_CONSTITUTION))
    pre = assess_behavior_motivation("他忽然决定辞职。", c)
    assert pre.ok is False
    assert pre.failure_type is FailureType.MISSING_MOTIVATION


# ============================================================
# 流水线编排（08）
# ============================================================


def _pipeline_fakes(
    *,
    initial_text: str,
    fixed_text: str | None = None,
    critic_scores: list[tuple[str, float, bool]],
    det_problems: list[str] | None = None,
):
    """构造 pipeline 的确定性 fake 实现。

    critic_scores: [(metric, score, passed), ...]；repair 后分数按 fixed_text 是否给出变化。
    """
    from app.creative.pipeline import CriticVerdict
    from app.creative.schemas import MetricName

    calls = {"round": 0, "critic_count": 0}

    async def writer() -> tuple[str, StateDelta]:
        return initial_text, StateDelta(text_anchors={})

    async def extract_state(text: str) -> StateDelta:
        return StateDelta(text_anchors={})

    async def det_check(delta: StateDelta) -> list[str]:
        return det_problems or []

    async def critic(text: str, delta: StateDelta) -> CriticVerdict:
        calls["critic_count"] += 1
        if fixed_text is not None and text == fixed_text:
            scores = [(m, s, True) for m, s, _p in critic_scores]
        else:
            scores = critic_scores
        # 多 metric 的 critic 由调用方分开；这里单 metric
        metric_name, score, passed = scores[0]
        return CriticVerdict(
            metric=MetricName(metric_name), score=score,
            threshold=0.85, passed=passed,
        )

    async def repair(diagnostic: DiagnosticReport, text: str) -> tuple[str, bool]:
        calls["round"] += 1
        if fixed_text is None:
            # 修复无效但声称已改：预算被消耗（用于验证 budget 耗尽分支）
            return text, True
        return fixed_text, True

    return writer, extract_state, det_check, [critic], repair, calls


@pytest.mark.asyncio
async def test_pipeline_passes_directly() -> None:
    from app.creative.pipeline import run_creative_pipeline

    writer, ext, det, critics, repair, _calls = _pipeline_fakes(
        initial_text="好文本", critic_scores=[("CVI", 0.92, True)]
    )
    r = await run_creative_pipeline(
        writer=writer, extract_state=ext, deterministic_check=det,
        critics=critics, repair_agent=repair,
    )
    assert r.passed is True
    assert r.quality_report is not None
    assert r.quality_report.character_value_integrity == 0.92


@pytest.mark.asyncio
async def test_pipeline_repair_once_then_pass() -> None:
    from app.creative.pipeline import run_creative_pipeline

    writer, ext, det, critics, repair, calls = _pipeline_fakes(
        initial_text="坏文本", fixed_text="修好的文本",
        critic_scores=[("CVI", 0.42, False)],
    )
    r = await run_creative_pipeline(
        writer=writer, extract_state=ext, deterministic_check=det,
        critics=critics, repair_agent=repair,
    )
    assert r.passed is True
    assert calls["round"] == 1
    assert len(r.repair_history) == 1
    assert r.repair_history[0].fixed is True


@pytest.mark.asyncio
async def test_pipeline_repair_budget_exhausted() -> None:
    """修复无效果（fixed_text=None）→ 预算耗尽 → HUMAN_REVIEW_REQUIRED。"""
    from app.creative.pipeline import PipelineConfig, run_creative_pipeline

    writer, ext, det, critics, repair, calls = _pipeline_fakes(
        initial_text="坏文本", critic_scores=[("CVI", 0.42, False)],
    )
    cfg = PipelineConfig(max_repair_rounds=2)
    r = await run_creative_pipeline(
        writer=writer, extract_state=ext, deterministic_check=det,
        critics=critics, repair_agent=repair,
        config=cfg,
    )
    assert r.status is GateVerdict.REVIEW_REQUIRED  # = HUMAN_REVIEW_REQUIRED
    assert calls["round"] == 2
    assert len(r.diagnostics) == 2


@pytest.mark.asyncio
async def test_pipeline_deterministic_fail_skips_critics() -> None:
    from app.creative.pipeline import run_creative_pipeline

    writer, ext, det, critics, repair, calls = _pipeline_fakes(
        initial_text="坏文本", critic_scores=[("CVI", 0.92, True)],
        det_problems=["时间线矛盾：第 2 章早于第 1 章"],
    )
    r = await run_creative_pipeline(
        writer=writer, extract_state=ext, deterministic_check=det,
        critics=critics, repair_agent=repair,
    )
    assert r.status is GateVerdict.REJECT
    assert calls["critic_count"] == 0  # 零 LLM 成本：确定性 FAIL 不进 Critic


# ============================================================
# Repair Agent（08 §8）
# ============================================================


def test_locality_check_small_fix_ok() -> None:
    from app.creative.repair_agent import locality_check

    original = (
        "通车那天他没有去剪彩。剪彩前夜，3 号墩的复检数据出来了，"
        "他带着报告去了桥墩现场。桥上风很大，他蹲在墩座旁，用手电筒照了照伸缩缝。"
        "天亮时，他把报告收进怀里，回宿舍睡了两小时，又起来上工了。"
    )
    repaired = (
        "通车那天他没有去剪彩。剪彩前夜，3 号墩的复检数据出来了，"
        "他带着报告去了桥墩现场。桥上风很大，他蹲在墩座旁，用手电筒照了照伸缩缝。"
        "天亮时，他把报告收进怀里，回宿舍睡了两小时，又起来上工了。"
        "中午他给妻子上了三炷香，然后继续巡查。"
    )
    ratio, ok = locality_check(original, repaired)
    assert ok is True
    assert ratio < 0.4


def test_locality_check_rewrite_rejected() -> None:
    from app.creative.repair_agent import locality_check

    original = (
        "通车那天他没有去剪彩。剪彩前夜，3 号墩的复检数据出来了，"
        "他带着报告去了桥墩现场。"
    )
    repaired = (
        "他辞职了，离开了这座城市。他坐火车去了南方，再也没有回来。"
        "多年以后，有人在一座陌生的桥上看见一个老人，说他像当年的陈工。"
    )
    _ratio, ok = locality_check(original, repaired)
    assert ok is False


@pytest.mark.asyncio
async def test_repair_agent_local_fix() -> None:
    from app.creative.diagnostic import make_diagnostic
    from app.creative.repair_agent import repair_chapter_text
    from app.creative.schemas import DiagnosticEvidence

    diagnostic = make_diagnostic(
        metric=MetricName.CVI, score=0.4, threshold=0.85,
        failure_type=FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE,
        chapter_no=7,
        evidence=[DiagnosticEvidence(text="因为想起亡妻", text_anchor="ch7/para-1",
                                     reason="动机仅引用情感")],
        retry_used=1,
    )

    original = (
        "通车那天他没有去剪彩。剪彩前夜，3 号墩的复检数据出来了，"
        "他带着报告去了桥墩现场。桥上风很大，他蹲在墩座旁检查伸缩缝，"
        "把复检结论写进报告。天亮时他回宿舍睡了两小时，又起来上工了。"
        "下午他巡查到 7 号墩，发现一处裂缝，用粉笔做了标记，"
        "打电话向值班室汇报，然后继续巡查下一段桥面。"
    )

    class _R:
        content = original + "走到桥中央时，他才想起妻子生前说过：桥通了，一起走一趟。"

    class _P:
        async def generate(self, prompt, model="mock", **kw):
            return _R()

    out = await repair_chapter_text(diagnostic, original, provider=_P(), model="mock")
    assert out.changed is True
    assert out.locality_ok is True
    assert "复检" in out.text


@pytest.mark.asyncio
async def test_repair_agent_rewrite_rejected() -> None:
    from app.creative.diagnostic import make_diagnostic
    from app.creative.repair_agent import repair_chapter_text
    from app.creative.schemas import DiagnosticEvidence

    diagnostic = make_diagnostic(
        metric=MetricName.CVI, score=0.4, threshold=0.85,
        failure_type=FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE,
        chapter_no=7,
        evidence=[DiagnosticEvidence(text="x", text_anchor="ch7/para-1", reason="y")],
        retry_used=1,
    )

    class _R:
        content = (
            "他辞职了，离开了这座城市。他坐火车去了南方，再也没有回来。"
            "多年以后，有人在一座陌生的桥上看见一个老人，说他像当年的陈工。"
        )

    class _P:
        async def generate(self, prompt, model="mock", **kw):
            return _R()

    original = (
        "通车那天他没有去剪彩。剪彩前夜，3 号墩的复检数据出来了，"
        "他带着报告去了桥墩现场。"
    )
    out = await repair_chapter_text(diagnostic, original, provider=_P(), model="mock")
    assert out.changed is False  # 全章重写被拒绝，保留原文
    assert out.text == original
    assert out.locality_ok is False


# ============================================================
# LLM Critic 检查器（07 §3.2）
# ============================================================


def test_parse_critic_json() -> None:
    from app.creative.critics.llm import parse_critic_json

    assert parse_critic_json('{"score": 0.9}') == {"score": 0.9}
    assert parse_critic_json('```json\n{"score": 0.9}\n```') == {"score": 0.9}
    assert parse_critic_json("前缀 {\"score\": 0.9} 后缀") == {"score": 0.9}
    assert parse_critic_json("完全不是 JSON") is None


class _JsonProvider:
    """返回固定 JSON 的 fake provider。"""

    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def generate(self, prompt, model="mock", **kw):
        class _R:
            content: str = self.payload

        return _R()


@pytest.mark.asyncio
async def test_cvi_critic_pass() -> None:
    from app.creative.critics.llm import cvi_critic

    v = await cvi_critic(
        _JsonProvider('{"score": 0.92, "failure_types": [], "evidence": []}'),
        "mock", "正文", "决策模型",
    )
    assert v.passed is True
    assert v.score == 0.92


@pytest.mark.asyncio
async def test_cvi_critic_fail_with_evidence() -> None:
    from app.creative.critics.llm import cvi_critic

    payload = (
        '{"score": 0.3, '
        '"failure_types": ["CHARACTER_VALUE_HIERARCHY_COLLAPSE"], '
        '"evidence": [{"text": "因为想起亡妻", "text_anchor": "ch7/para-1", '
        '"reason": "动机仅引用情绪"}]}'
    )
    v = await cvi_critic(_JsonProvider(payload), "mock", "正文", "决策模型")
    assert v.passed is False
    assert v.failure_type is FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE
    assert v.evidence[0].text_anchor == "ch7/para-1"


@pytest.mark.asyncio
async def test_critic_non_json_conservative_fail() -> None:
    """critic 输出非 JSON → 保守 FAIL（不放过问题）。"""
    from app.creative.critics.llm import cci_critic

    v = await cci_critic(_JsonProvider("文笔很好！"), "mock", "正文")
    assert v.passed is False
    assert v.score == 0.0
    assert v.evidence
    assert "非 JSON" in v.evidence[0].reason


@pytest.mark.asyncio
async def test_theme_critic_verdict() -> None:
    from app.creative.critics.llm import theme_critic

    v = await theme_critic(
        _JsonProvider('{"emergence_score": 0.8, "failure_types": [], "evidence": []}'),
        "mock", "正文",
    )
    assert v.passed is True
    assert v.emergence_score == 0.8

    bad = await theme_critic(
        _JsonProvider('{"emergence_score": 0.2, "failure_types": ["THEME_FORCED_ACTION"]}'),
        "mock", "正文",
    )
    assert bad.passed is False
    assert FailureType.THEME_FORCED_ACTION in bad.failure_types


# ============================================================
# 反事实人物测试（07 §6）
# ============================================================


@pytest.mark.asyncio
async def test_counterfactual_parses_and_flags_downgrade() -> None:
    from app.creative.critics.counterfactual import run_counterfactual_tests

    payload = (
        '{"drop_emotion_object": false, "drop_theme": true, '
        '"change_profession": false, "change_value_hierarchy": false, '
        '"substitute_relation": false}'
    )
    out = await run_counterfactual_tests(
        _JsonProvider(payload), "mock",
        behavior="缺席剪彩", constitution=CharacterConstitution(**dict(_BASE_CONSTITUTION)),
    )
    assert out.ok is True
    assert out.downgraded is True  # A 失败：删除情感对象行为不成立
    assert out.generic_character is True  # C/D/E 全不变：职业/价值/关系未参与


@pytest.mark.asyncio
async def test_counterfactual_non_json() -> None:
    from app.creative.critics.counterfactual import run_counterfactual_tests

    out = await run_counterfactual_tests(
        _JsonProvider("无法判定"), "mock",
        behavior="x", constitution=CharacterConstitution(**dict(_BASE_CONSTITUTION)),
    )
    assert out.ok is False
    assert out.result.drop_emotion_object is None


# ============================================================
# Semantic Explorer（07 §7 语义扩展 + 多样性门）
# ============================================================


@pytest.mark.asyncio
async def test_explorer_diverse_directions_pass() -> None:
    from app.creative.explorer import explore_semantic_directions

    payload = (
        '{"directions": ['
        '{"id": "城市排水", "keywords": ["排水","管网","内涝","泵站"], '
        '"hook": "梅雨导致铁路限速"},'
        '{"id": "工程检测", "keywords": ["桥梁","伸缩缝","病害","复检"], '
        '"hook": "汛前桥梁全面检测"},'
        '{"id": "铁路调度", "keywords": ["信号","调度","限速","防汛"], '
        '"hook": "调度员连夜盯守"}]}'
    )
    directions, verdict, detail = await explore_semantic_directions(
        _JsonProvider(payload), "mock", "烟雨朦胧"
    )
    assert directions is not None
    assert len(directions) == 3
    assert verdict is not None
    assert verdict.passed is True
    assert "成功" in detail


@pytest.mark.asyncio
async def test_explorer_first_association_retries_then_accepts() -> None:
    """第一版同质簇（不过）→ 重试换方向 → 通过。"""
    from app.creative.explorer import explore_semantic_directions

    class _SeqProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, prompt, model="mock", **kw):
            self.calls += 1
            if self.calls == 1:
                return _R(
                    '{"directions": [{"id": "江南", "keywords": ["江南","烟雨","油纸伞"]},'
                    '{"id": "雨巷", "keywords": ["烟雨","雨巷","青石板"]},'
                    '{"id": "水乡", "keywords": ["烟雨","水乡","旧桥"]}]}'
                )
            return _R(
                '{"directions": [{"id": "城市排水", "keywords": ["排水","管网","内涝"]},'
                '{"id": "工程检测", "keywords": ["桥梁","伸缩缝","复检"]},'
                '{"id": "铁路调度", "keywords": ["信号","调度","限速"]}]}'
            )

    directions, verdict, detail = await explore_semantic_directions(
        _SeqProvider(), "mock", "烟雨朦胧"
    )
    assert directions is not None
    assert verdict is not None
    assert verdict.passed is True
    assert "成功" in detail


class _R:
    """返回固定 content 的轻量结果对象（模块级，供 fake provider 复用）。"""

    def __init__(self, content: str) -> None:
        self.content = content


# ============================================================
# P3-1：generate_chapter draft_mode 集成（story_gate）
# ============================================================


class _RoutingProvider:
    """按 system prompt 特征路由的 fake provider（writer/critic/repair 各司其职）。"""

    def __init__(self, *, writer_text: str, critic: dict[str, str], repair_text: str = ""):
        self.writer_text = writer_text
        self.critic = critic
        self.repair_text = repair_text
        self.repair_calls = 0

    async def generate(self, prompt, model="mock", **kw):
        system = kw.get("system") or ""
        if "人物价值完整性评审" in system:
            return _R(self.critic.get("cvi", '{"score": 0.9, "failure_types": [], "evidence": []}'))
        if "人物自主性评审" in system:
            return _R(self.critic.get("cai", '{"score": 0.9, "failure_types": [], "evidence": []}'))
        if "因果连贯性评审" in system:
            return _R(self.critic.get("cci", '{"score": 0.9, "failure_types": [], "evidence": []}'))
        if "世界一致性评审" in system:
            default_wci = '{"score": 0.95, "failure_types": [], "evidence": []}'
            return _R(self.critic.get("wci", default_wci))
        if "修复编辑" in system:
            self.repair_calls += 1
            return _R(self.repair_text or prompt)
        return _R(self.writer_text)


def _fake_cards(*names: str) -> list[tuple[str, dict]]:
    return [
        (f"asset-{i}", {
            "name": n, "description": f"{n}的外观", "personality": "温柔",
            "scenario": "桥", "first_mes": "你好", "mes_example": "",
            "alternate_greetings": [], "system_prompt": "", "post_history_instructions": "",
            "creator_notes": "", "tags": [], "character_book": {}, "talkativeness": 0.5,
            "depth_prompt": {},
        })
        for i, n in enumerate(names)
    ]


async def _run_draft_mode(
    db_session, monkeypatch, *, provider: _RoutingProvider
) -> dict:
    from types import SimpleNamespace

    import app.services.roleplay as rp_mod
    from app.services import story_forge as sf_mod

    async def _fake_resolver(db, model):
        return SimpleNamespace(provider=provider, model="mock")

    async def _fake_load_cards(db, uid, ids):
        return _fake_cards("陈工", "梁工")

    monkeypatch.setattr(rp_mod, "_load_cards", _fake_load_cards)
    monkeypatch.setattr(sf_mod.roleplay, "_load_cards", _fake_load_cards)
    monkeypatch.setattr(sf_mod, "resolve_text_provider", _fake_resolver)

    db = db_session
    p = await sf_mod.create_project(db, "u1", title="桥的故事", synopsis="守桥人", genre="现实主义")
    c = await sf_mod.create_chapter(db, "u1", p.id, title="通车日", outline="缺席剪彩")
    result = await sf_mod.generate_chapter(db, "u1", p.id, c.id, draft_mode=True)
    return result, c


@pytest.mark.asyncio
async def test_draft_mode_passes_and_records_report(
    db_session, monkeypatch
) -> None:
    """L0 全过 → done + notes.quality_report。"""
    provider = _RoutingProvider(
        writer_text=(
            "通车那天他没有去剪彩。剪彩前夜，3 号墩的复检数据出来了，"
            "他带着报告去了桥墩现场，检查完伸缩缝，在报告上签了字。"
        ),
        critic={},
    )
    result, chapter = await _run_draft_mode(db_session, monkeypatch, provider=provider)
    assert "error" not in result, result
    assert result["status"] == "done"
    assert result["quality_report"] is not None
    assert result["quality_report"]["character_value_integrity"] == 0.9
    assert provider.repair_calls == 0  # 全过不修复

    got = await _get_chapter(db_session, chapter.id)
    assert got is not None
    assert got.status == "done"
    notes = _json_load(got.notes)
    assert notes.get("quality_report") is not None


@pytest.mark.asyncio
async def test_draft_mode_repair_then_review(
    db_session, monkeypatch
) -> None:
    """L0 FAIL → 修复无效 → 预算耗尽 → status=review（正文不落库为 done）。"""
    writer_text = (
        "通车那天他没有去剪彩。剪彩前夜，3 号墩的复检数据出来了，"
        "他带着报告去了桥墩现场，检查完伸缩缝，在报告上签了字。"
        "天亮时他回宿舍睡了两小时，又起来上工了。"
        "下午他巡查到 7 号墩，发现一处裂缝，用粉笔做了标记，"
        "打电话向值班室汇报，然后继续巡查下一段桥面。"
    )
    provider = _RoutingProvider(
        writer_text=writer_text,
        critic={
            "cvi": '{"score": 0.3, "failure_types": ["CHARACTER_VALUE_HIERARCHY_COLLAPSE"], '
                   '"evidence": [{"text": "因为想起亡妻", "text_anchor": "ch1", "reason": "x"}]}',
            "cai": '{"score": 0.2, "failure_types": ["PLOT_FORCED_ACTION"], "evidence": []}',
        },
        repair_text=writer_text + "走到桥中央时，他才想起妻子生前说过：桥通了，一起走一趟。",
    )
    result, chapter = await _run_draft_mode(db_session, monkeypatch, provider=provider)
    assert "error" not in result, result
    assert result["status"] == "review"
    assert provider.repair_calls == 2  # 预算 2 轮
    assert len(result.get("repair_history", [])) == 2

    got = await _get_chapter(db_session, chapter.id)
    assert got is not None
    assert got.status == "review"


async def _get_chapter(db_session, chapter_id: str):
    from app.models.story_chapter import StoryChapter
    from sqlalchemy import select

    return (
        await db_session.execute(
            select(StoryChapter).where(StoryChapter.id == chapter_id)
        )
    ).scalar_one_or_none()


def _json_load(raw: str) -> dict:
    import json as _json

    try:
        return _json.loads(raw or "{}")
    except Exception:
        return {}


# ============================================================
# DiagnosticReport（06 §4 schema 完整性）
# ============================================================


def test_diagnostic_report_schema() -> None:
    r = DiagnosticReport(
        status=GateVerdict.REJECT,
        metric=MetricName.CVI,
        score=0.42,
        threshold=0.85,
        failure_type=FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE,
        severity=Severity.CRITICAL,
        chapter_no=7,
        evidence=[{"text": "通车那天他没去剪彩，因为想起亡妻。",
                   "text_anchor": "ch7/para-12", "reason": "动机仅引用情绪触发器"}],
        violations=[{"rule": "Value Preservation", "detail": "行为违反最高价值"}],
    )
    assert r.failure_type.value == "CHARACTER_VALUE_HIERARCHY_COLLAPSE"
    assert r.status is GateVerdict.REJECT
    assert len(r.evidence) == 1
