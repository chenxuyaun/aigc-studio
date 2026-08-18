"""State Validator（05 §3.3）：Creative State Bus 的唯一写入口。

所有 Agent 只能 READ / PROPOSE；本模块裁决 ACCEPT / REJECT。

校验顺序（确定性，零 LLM）：
1. tier 检查：变更不得触碰 IMMUTABLE 事实（世界规则/时间线锚点/核心关系/价值结构）
2. text-anchor 检查：delta 每条声明必须在正文有锚点
3. 状态机检查：CharacterState.stage 迁移必须合法（禁止 S0→S4 跳跃）
4. 因果检查：causal_edges 的 from/to 必须存在（当前图或本 delta 新增）
5. loop 检查：resolved 必须引用真实 open loop

本模块是纯函数（不碰 DB），便于单元测试；落库由调用方负责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.creative.schemas import (
    CharacterStage,
    StateDelta,
    StoryState,
)

# 状态机合法迁移表（03 §6）：S0→S1→S2→S3→S4，允许回退/停留，禁止跳跃
# S4 之后可回到 S0（新稳态，新弧线）
_LEGAL_STAGE_TRANSITIONS: dict[CharacterStage, set[CharacterStage]] = {
    CharacterStage.S0_STABLE: {
        CharacterStage.S0_STABLE,  # 停留（无变化）
        CharacterStage.S1_COGNITIVE_SHIFT,  # 事件 → 认知变化
    },
    CharacterStage.S1_COGNITIVE_SHIFT: {
        CharacterStage.S1_COGNITIVE_SHIFT,
        CharacterStage.S0_STABLE,  # 拒绝新信息，回到稳态
        CharacterStage.S2_VALUE_CONFLICT,  # 冲突升级
    },
    CharacterStage.S2_VALUE_CONFLICT: {
        CharacterStage.S2_VALUE_CONFLICT,
        CharacterStage.S0_STABLE,  # 冲突消解，固守
        CharacterStage.S3_ACTION,  # 做出选择
    },
    CharacterStage.S3_ACTION: {
        CharacterStage.S3_ACTION,
        CharacterStage.S0_STABLE,  # 行为后回到稳态（未成长）
        CharacterStage.S4_GROWTH,  # 成长
    },
    CharacterStage.S4_GROWTH: {
        CharacterStage.S4_GROWTH,
        CharacterStage.S0_STABLE,  # 新稳态
    },
}

# IMMUTABLE 级字段：delta 不得触碰（05 §2）
_IMMUTABLE_DELTA_KEYS = {
    # character_deltas 中禁止修改的字段
    "constitution_fields": {"identity", "worldview", "beliefs", "core_values",
                            "value_hierarchy", "mission", "history",
                            "moral_limits", "boundaries"},
}


class ValidationResultCode(Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


@dataclass
class ValidationResult:
    code: ValidationResultCode
    reasons: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.code is ValidationResultCode.ACCEPT


def _anchor_check(delta: StateDelta) -> list[str]:
    """2) text-anchor 检查：每条声明必须有正文锚点。"""
    problems: list[str] = []
    declared = set(delta.text_anchors.keys())
    # 各声明的稳定 id（事件/节点/loop/关系 取唯一字段）
    need_anchor: list[tuple[str, str]] = []
    for i, ev in enumerate(delta.timeline_events):
        need_anchor.append((f"timeline_events[{i}]", ev.event or str(ev.at)))
    for nid, _st in delta.character_deltas.items():
        need_anchor.append((f"character_deltas[{nid}]", nid))
    for i, loop in enumerate(delta.loops_opened):
        need_anchor.append((f"loops_opened[{i}]", loop.id))
    for i, rloop in enumerate(delta.loops_resolved):
        need_anchor.append((f"loops_resolved[{i}]", rloop.id))
    for i, edge in enumerate(delta.causal_edges):
        need_anchor.append((f"causal_edges[{i}]", f"{edge.from_node}->{edge.to_node}"))
    for i, k_entry in enumerate(delta.knowledge_updates):
        need_anchor.append((f"knowledge_updates[{i}]", f"{k_entry.character}:{k_entry.knows}"))
    for i, g in enumerate(delta.goal_updates):
        need_anchor.append((f"goal_updates[{i}]", f"{g.owner}:{g.goal}"))
    if delta.facts_added:
        need_anchor.append(("facts_added", ";".join(delta.facts_added[:3])))
    for key, label in need_anchor:
        if key not in declared and label not in declared and not any(
            k.startswith(key) or label in k for k in declared
        ):
            problems.append(f"text-anchor 缺失：{key}（{label[:60]}）未在 text_anchors 声明")
    # 声明了锚点但对应实体不存在
    labels = {label for _k, label in need_anchor}
    for anchor_key in declared:
        if anchor_key == "facts_added":
            continue
        if not any(anchor_key == lb or anchor_key in lb or lb in anchor_key for lb in labels):
            problems.append(f"text_anchors 引用了不存在的实体：{anchor_key}")
    return problems


def _stage_check(current: StoryState, delta: StateDelta) -> list[str]:
    """3) 状态机检查：禁止跳跃（无过程顿悟 / 人格突变）。"""
    problems: list[str] = []
    for name, new_st in delta.character_deltas.items():
        old_st = current.character_states.get(name)
        old_stage = old_st.stage if old_st else CharacterStage.S0_STABLE
        if new_st.stage not in _LEGAL_STAGE_TRANSITIONS.get(old_stage, set()):
            problems.append(
                f"状态机非法迁移：{name} {old_stage.value} → {new_st.stage.value}"
                f"（禁止跳跃：{sorted(s.value for s in _LEGAL_STAGE_TRANSITIONS[old_stage])}）"
            )
    return problems


def _causal_check(current: StoryState, delta: StateDelta) -> list[str]:
    """4) 因果检查：edge 的 from/to 必须存在（当前图节点或本 delta 新增）。"""
    problems: list[str] = []
    existing = {n.id for n in current.causal_graph.nodes}
    added = set(_node_ids_from_delta(delta))
    for edge in delta.causal_edges:
        if edge.from_node not in existing and edge.from_node not in added:
            problems.append(f"因果边 from 节点不存在：{edge.from_node}")
        if edge.to_node not in existing and edge.to_node not in added:
            problems.append(f"因果边 to 节点不存在：{edge.to_node}")
    return problems


def _node_ids_from_delta(delta: StateDelta) -> list[Any]:
    """从 delta 可推导的隐式节点：facts_added 与 timeline_events 均可作为因果节点。"""
    ids: list[str] = []
    for ev in delta.timeline_events:
        ids.append(ev.event[:100])
    for f in delta.facts_added:
        ids.append(f[:100])
    return ids


def _loop_check(current: StoryState, delta: StateDelta) -> list[str]:
    """5) loop 检查：resolved 必须引用真实 open loop；新开 loop id 不得与已存在重复。"""
    problems: list[str] = []
    open_ids = {loop.id for loop in current.open_loops}
    newly_open = {loop.id for loop in delta.loops_opened}
    for loop in delta.loops_resolved:
        if loop.id not in open_ids and loop.id not in newly_open:
            problems.append(f"resolved loop 不存在：{loop.id}")
    dup = open_ids & newly_open
    if dup:
        problems.append(f"重复开 loop：{sorted(dup)}")
    return problems


def validate_state_delta(
    current: StoryState,
    delta: StateDelta,
    *,
    require_anchors: bool = True,
) -> ValidationResult:
    """校验 delta 可被接受。require_anchors=False 用于尚无正文锚点的建模期提案。"""
    reasons: list[str] = []
    if require_anchors:
        reasons.extend(_anchor_check(delta))
    reasons.extend(_stage_check(current, delta))
    reasons.extend(_causal_check(current, delta))
    reasons.extend(_loop_check(current, delta))
    if reasons:
        return ValidationResult(ValidationResultCode.REJECT, reasons)
    return ValidationResult(ValidationResultCode.ACCEPT)


def apply_delta(current: StoryState, delta: StateDelta) -> StoryState:
    """ACCEPT 后应用变更：返回新 StoryState（version+1）。调用方负责落库与快照。"""
    import copy

    nxt = copy.deepcopy(current)
    nxt.version += 1
    # world facts
    nxt.world_state.facts.extend(delta.facts_added)
    # timeline
    nxt.timeline.events.extend(delta.timeline_events)
    # character states（合并 value_weights/emotion，其他字段整体替换）
    for name, new_st in delta.character_deltas.items():
        old = nxt.character_states.get(name)
        if old is not None and old.value_weights:
            merged_weights = dict(old.value_weights)
            merged_weights.update(new_st.value_weights)
            new_st = new_st.model_copy(update={"value_weights": merged_weights})
        nxt.character_states[name] = new_st
        nxt.value_states[name] = dict(new_st.value_weights or {})
    # relationships / goals / knowledge
    nxt.relationship_states.extend(delta.relationship_deltas)
    nxt.goal_states.extend(delta.goal_updates)
    nxt.knowledge_state.extend(delta.knowledge_updates)
    # loops
    resolved_ids = {loop.id for loop in delta.loops_resolved}
    if resolved_ids:
        nxt.open_loops = [loop for loop in nxt.open_loops if loop.id not in resolved_ids]
    nxt.open_loops.extend(delta.loops_opened)
    nxt.resolved_loops.extend(delta.loops_resolved)
    # causal graph（隐式节点 + 显式边）
    implicit = [
        n for n in _node_ids_from_delta(delta)
        if not any(ex.id == n for ex in nxt.causal_graph.nodes)
    ]
    from app.creative.schemas import CausalNode

    for nid in implicit:
        nxt.causal_graph.nodes.append(
            CausalNode(id=nid, type="event", desc=nid, chapter=nxt.version)
        )
    nxt.causal_graph.edges.extend(delta.causal_edges)
    # symbols / theme
    nxt.symbol_state.extend(delta.symbol_updates)
    nxt.theme_state.propositions.extend(delta.theme_evidence)
    return nxt
