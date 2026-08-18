"""CVI 确定性预检（04 §3 的 L0 前置层，零 LLM）。

在 LLM Critic 之前先跑：对"重大行为"做动机链的价值参与启发式判定。
直接服务 REGRESSION_CASE_001（桥的名字）：
  - 行为解释含价值信号（价值名/职业行为词）→ 价值参与 OK
  - 行为解释只有情感/关系信号 → CHARACTER_VALUE_HIERARCHY_COLLAPSE 嫌疑
  - 两者皆无 → MISSING_MOTIVATION 嫌疑

注意：本模块是**预检**（启发式，可能误报），最终判定由 LLM CVI Critic 确认；
但预检命中 COLLAPSE 的，若无价值信号则优先判 FAIL（启发式保守方向）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.creative.schemas import CharacterConstitution, FailureType

# 职业行为信号词（价值参与叙事的代理信号，07 §5 深度信号扩展）
_PROFESSION_SIGNAL_WORDS: tuple[str, ...] = (
    "复检", "检查", "报告", "数据", "规程", "流程", "验收", "安全",
    "责任", "标准", "原则", "底线", "评估", "检测", "隐患", "荷载",
    "签字", "记录", "审查", "复核", "巡检", "维修", "施工", "设计",
)


@dataclass
class MotivationPrecheck:
    behavior: str = ""
    value_signals: list[str] = field(default_factory=list)
    emotion_signals: list[str] = field(default_factory=list)
    ok: bool = True
    failure_type: FailureType | None = None
    score: float = 1.0  # 预检分（LLM Critic 会修正）
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "behavior": self.behavior,
            "value_signals": self.value_signals,
            "emotion_signals": self.emotion_signals,
            "ok": self.ok,
            "failure_type": self.failure_type.value if self.failure_type else None,
            "score": self.score,
            "detail": self.detail,
        }


def _match_terms(text: str, terms: list[str], *, loose: bool = False) -> list[str]:
    """术语匹配。loose=False（价值信号）：精确匹配；
    loose=True（情感/关系信号）：任一字符命中即算（妻子→亡妻含「妻」）。

    价值信号从严格（防漏报 COLLAPSE 的保守方向），情感信号从宽。
    """
    hits: list[str] = []
    for t in terms:
        t = t.strip()
        if not t:
            continue
        if t in text:
            hits.append(t)
            continue
        if loose and any(ch in text for ch in t if ch.strip()):
            hits.append(t)
    return hits


def assess_behavior_motivation(
    behavior: str, constitution: CharacterConstitution
) -> MotivationPrecheck:
    """评估单条重大行为的动机价值参与（启发式预检）。"""
    pre = MotivationPrecheck(behavior=behavior)
    if not behavior.strip():
        pre.ok = False
        pre.failure_type = FailureType.MISSING_MOTIVATION
        pre.score = 0.0
        pre.detail = "行为描述为空，无法评估"
        return pre

    # 价值信号：value_hierarchy 键 + 职业行为词（精确匹配）
    value_terms = list(constitution.value_hierarchy.keys()) + list(_PROFESSION_SIGNAL_WORDS)
    pre.value_signals = _match_terms(behavior, value_terms)

    # 情感/关系信号：情绪触发器 + 关系名（宽松匹配，关系名核心字如「妻」）
    emotion_terms = list(constitution.emotional_triggers)
    emotion_terms += [r.name for r in constitution.relationships]
    pre.emotion_signals = _match_terms(behavior, emotion_terms, loose=True)

    if pre.value_signals:
        pre.ok = True
        pre.score = 1.0
        pre.detail = f"价值参与在场（{pre.value_signals[:3]}）"
    elif pre.emotion_signals:
        pre.ok = False
        pre.failure_type = FailureType.CHARACTER_VALUE_HIERARCHY_COLLAPSE
        pre.score = 0.3
        pre.detail = (
            f"行为解释仅含情感/关系信号（{pre.emotion_signals[:3]}），"
            f"价值层级未参与（{sorted(constitution.value_hierarchy.keys())[:3]}…）："
            "疑似价值层级崩塌（情绪触发器取代核心价值）"
        )
    else:
        pre.ok = False
        pre.failure_type = FailureType.MISSING_MOTIVATION
        pre.score = 0.2
        pre.detail = "行为解释既无价值信号也无情感信号：动机链缺失"
    return pre


def precheck_chapter_motivations(
    behaviors: list[str], constitution: CharacterConstitution
) -> list[MotivationPrecheck]:
    """批量预检一章中的多条重大行为。"""
    return [assess_behavior_motivation(b, constitution) for b in behaviors]
