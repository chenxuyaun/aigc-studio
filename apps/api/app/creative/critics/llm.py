"""LLM Critic 检查器（07 §3.2）：L0 四指标 + Theme 的独立 LLM 判定。

设计约束（独立批判）：
- 每个 critic 是独立 prompt 角色，**不携带 writer 的自我辩解**（与 writer 上下文隔离）
- 输出严格 JSON（schema 固定），宽容解析（损坏 → 返回保守 FAIL + 解析失败证据）
- temperature 固定低（0.2），减少随机

P3 接入真实 provider；测试用 fake provider（返回固定 JSON）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.creative.pipeline import CriticVerdict
from app.creative.schemas import DiagnosticEvidence, FailureType, MetricName

_CRITIC_TEMPERATURE = 0.2


def parse_critic_json(raw: str) -> dict[str, Any] | None:
    """宽容解析 critic 输出：取第一个 JSON 对象；失败返回 None。"""
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if 0 <= start < end:
            try:
                data = json.loads(cleaned[start : end + 1])
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _evidence_from(data: dict[str, Any], key: str = "evidence") -> list[DiagnosticEvidence]:
    items = data.get(key) or []
    out: list[DiagnosticEvidence] = []
    for it in items[:10]:
        if isinstance(it, dict):
            out.append(
                DiagnosticEvidence(
                    text=str(it.get("text") or "")[:2000],
                    text_anchor=str(it.get("text_anchor") or "")[:200],
                    reason=str(it.get("reason") or "")[:1000],
                )
            )
    return out


def _failure_types_from(data: dict[str, Any], key: str = "failure_types") -> list[FailureType]:
    out: list[FailureType] = []
    for ft in (data.get(key) or [])[:5]:
        try:
            out.append(FailureType(str(ft)))
        except ValueError:
            continue
    return out


def _verdict(
    metric: MetricName,
    data: dict[str, Any],
    threshold: float,
    *,
    fallback_failure: FailureType,
) -> CriticVerdict:
    """解析后的 CriticVerdict；score 缺失/越界 → 保守 FAIL。"""
    try:
        score = float(data.get("score", 0.0))
        score = max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        score = 0.0
    passed = score >= threshold
    failure_types = _failure_types_from(data)
    if not passed and not failure_types:
        failure_types = [fallback_failure]
    return CriticVerdict(
        metric=metric,
        score=score,
        threshold=threshold,
        passed=passed,
        failure_type=failure_types[0] if failure_types else None,
        evidence=_evidence_from(data),
    )


async def _ask_critic(
    provider: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[dict[str, Any] | None, str]:
    """单次 critic LLM 调用，返回 (解析后 JSON, 原始文本)。"""
    result = await provider.generate(
        user_prompt, model, system=system_prompt, temperature=_CRITIC_TEMPERATURE
    )
    raw = (getattr(result, "content", "") or "").strip()
    return parse_critic_json(raw), raw


async def cvi_critic(
    provider: Any,
    model: str,
    content: str,
    constitution_block: str,
    *,
    threshold: float = 0.85,
) -> CriticVerdict:
    """CVI：人物价值完整性（04 §3）。行为是否符合价值结构、情绪是否越权。"""
    system = (
        "你是独立的人物价值完整性评审（CVI）。审查章节中人物行为是否与其价值结构一致。\n"
        "检查：1) 价值保持（重大行为不违反最高价值且无冲突剧情）；"
        "2) 动机对齐（重大行为有价值动机链）；"
        "3) 情绪越权（情绪触发器不得取代核心价值决定重大行为）；"
        "4) 价值无过程翻转。\n"
        "输出严格 JSON（不要任何多余文字）：\n"
        '{"score": 0-1, "failure_types": ["CHARACTER_VALUE_HIERARCHY_COLLAPSE"等], '
        '"evidence": [{"text": "原句", "text_anchor": "段落定位", "reason": "违反哪条"}]}\n'
        "failure_types 从字典取：CHARACTER_VALUE_HIERARCHY_COLLAPSE / MOTIVATION_DOWNGRADE / "
        "EMOTIONAL_OVERRIDE / MISSING_MOTIVATION / VALUE_FLIP_WITHOUT_PROCESS / GENERIC_CHARACTER"
    )
    user = (
        f"【人物决策模型】\n{constitution_block}\n\n"
        f"【章节正文】\n{content[:6000]}\n\n请评审并输出 JSON。"
    )
    data, raw = await _ask_critic(provider, model, system, user)
    if data is None:
        return CriticVerdict(
            MetricName.CVI, 0.0, threshold, False,
            failure_type=FailureType.MISSING_MOTIVATION,
            evidence=[DiagnosticEvidence(text=raw[:200], text_anchor="critic-parse",
                                         reason="critic 输出非 JSON")],
        )
    return _verdict(MetricName.CVI, data, threshold,
                    fallback_failure=FailureType.MISSING_MOTIVATION)


async def cai_critic(
    provider: Any,
    model: str,
    content: str,
    *,
    threshold: float = 0.85,
) -> CriticVerdict:
    """CAI：人物自主性（04 §5）。人物自己推动故事，而非被剧情/主题/情绪推动。"""
    system = (
        "你是独立的人物自主性评审（CAI）。判断人物是否自己推动故事。\n"
        "检测五类强制行动：PLOT_FORCED_ACTION（剧情强迫）/ THEME_FORCED_ACTION（主题强迫）/ "
        "EMOTION_FORCED_ACTION（情绪强迫）/ AUTHORIAL_FORCED_ACTION（作者解释腔）/ "
        "COINCIDENCE_DEPENDENCY（巧合依赖）。\n"
        "若某重大行为的唯一理由是「这样故事会更感人」→ 直接 FAIL。\n"
        "输出严格 JSON："
        '{"score": 0-1, "failure_types": [...], '
        '"evidence": [{"text", "text_anchor", "reason"}]}'
    )
    user = f"【章节正文】\n{content[:6000]}\n\n请评审并输出 JSON。"
    data, raw = await _ask_critic(provider, model, system, user)
    if data is None:
        return CriticVerdict(
            MetricName.CAI, 0.0, threshold, False,
            failure_type=FailureType.PLOT_FORCED_ACTION,
            evidence=[DiagnosticEvidence(text=raw[:200], text_anchor="critic-parse",
                                         reason="critic 输出非 JSON")],
        )
    return _verdict(MetricName.CAI, data, threshold,
                    fallback_failure=FailureType.PLOT_FORCED_ACTION)


async def cci_critic(
    provider: Any,
    model: str,
    content: str,
    causal_summary: str = "",
    *,
    threshold: float = 0.85,
) -> CriticVerdict:
    """CCI：因果连贯（06 §2.3）。事件链完整、无巧合堆叠、无事后补解释。"""
    system = (
        "你是独立的因果连贯性评审（CCI）。判断重要事件之间是否有完整因果关系。\n"
        "检查：causal leap（因果跳跃）/ missing motivation（动机缺失）/ "
        "coincidence overload（巧合过载）/ forced twist（强行反转）/ "
        "retroactive justification（事后补解释）/ plot convenience（剧情便利）。\n"
        "输出严格 JSON："
        '{"score": 0-1, "failure_types": [...], '
        '"evidence": [{"text", "text_anchor", "reason"}]}'
    )
    user = (
        f"【因果图摘要】\n{causal_summary or '（未提供）'}\n\n"
        f"【章节正文】\n{content[:6000]}\n\n请评审并输出 JSON。"
    )
    data, raw = await _ask_critic(provider, model, system, user)
    if data is None:
        return CriticVerdict(
            MetricName.CCI, 0.0, threshold, False,
            failure_type=FailureType.CAUSAL_LEAP,
            evidence=[DiagnosticEvidence(text=raw[:200], text_anchor="critic-parse",
                                         reason="critic 输出非 JSON")],
        )
    return _verdict(MetricName.CCI, data, threshold,
                    fallback_failure=FailureType.CAUSAL_LEAP)


async def wci_critic(
    provider: Any,
    model: str,
    content: str,
    world_summary: str = "",
    *,
    threshold: float = 0.90,
) -> CriticVerdict:
    """WCI：世界一致性（06 §2.4）。世界规则/时间线/知识边界/事实一致。"""
    system = (
        "你是独立的世界一致性评审（WCI）。判断章节是否违反世界规则/时间线/知识边界。\n"
        "检查：rule preservation（世界规则）/ timeline consistency（时间线）/ "
        "knowledge consistency（知识边界，谁不知道什么）/ fact consistency（事实记忆）。\n"
        "输出严格 JSON："
        '{"score": 0-1, "failure_types": [...], '
        '"evidence": [{"text", "text_anchor", "reason"}]}'
    )
    user = (
        f"【世界设定】\n{world_summary or '（未提供）'}\n\n"
        f"【章节正文】\n{content[:6000]}\n\n请评审并输出 JSON。"
    )
    data, raw = await _ask_critic(provider, model, system, user)
    if data is None:
        return CriticVerdict(
            MetricName.WCI, 0.0, threshold, False,
            failure_type=FailureType.TIMELINE_CONFLICT,
            evidence=[DiagnosticEvidence(text=raw[:200], text_anchor="critic-parse",
                                         reason="critic 输出非 JSON")],
        )
    return _verdict(MetricName.WCI, data, threshold,
                    fallback_failure=FailureType.TIMELINE_CONFLICT)


@dataclass
class ThemeVerdict:
    """Theme Guard 判定：主题涌现度 + 入侵证据（软门，不进 L0 硬门）。"""

    emergence_score: float = 0.0
    passed: bool = False
    failure_types: list[FailureType] = field(default_factory=list)
    evidence: list[DiagnosticEvidence] = field(default_factory=list)
    threshold: float = 0.6

    def as_dict(self) -> dict[str, Any]:
        return {
            "emergence_score": round(self.emergence_score, 3),
            "passed": self.passed,
            "failure_types": [f.value for f in self.failure_types],
            "evidence": [e.model_dump() for e in self.evidence],
        }


async def theme_critic(
    provider: Any,
    model: str,
    content: str,
    theme_propositions: str = "",
    *,
    threshold: float = 0.6,
) -> ThemeVerdict:
    """Theme Guard（07 §4）：主题入侵检测 + 主题涌现评估。

    emergence_score = 主题由人物选择驱动的程度（≥threshold 视为健康涌现）。
    """
    system = (
        "你是主题守卫评审。主题必须通过人物选择产生，人物不得为表达主题而行动。\n"
        "检测：THEME_FORCED_ACTION（为表现奉献而牺牲/为表现爱而等待十年/为表现家国而放弃爱情，"
        "且无价值结构支撑）/ THEME_EXPOSITION（叙述者直接点题说教）。\n"
        "对每个疑似主题强迫的行动追问：为什么是这个人物？这个选择来自他的价值结构吗？\n"
        "输出严格 JSON："
        '{"emergence_score": 0-1（主题涌现度，人物驱动=高）, "failure_types": [...], '
        '"evidence": [{"text", "text_anchor", "reason"}]}'
    )
    user = (
        f"【主题命题】\n{theme_propositions or '（未提供）'}\n\n"
        f"【章节正文】\n{content[:6000]}\n\n请评审并输出 JSON。"
    )
    data, raw = await _ask_critic(provider, model, system, user)
    if data is None:
        return ThemeVerdict(
            emergence_score=0.0, passed=False,
            failure_types=[FailureType.THEME_FORCED_ACTION],
            evidence=[DiagnosticEvidence(text=raw[:200], text_anchor="critic-parse",
                                         reason="critic 输出非 JSON")],
            threshold=threshold,
        )
    try:
        score = float(data.get("emergence_score", 0.0))
        score = max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        score = 0.0
    failure_types = _failure_types_from(data)
    if score < threshold and not failure_types:
        failure_types = [FailureType.THEME_FORCED_ACTION]
    return ThemeVerdict(
        emergence_score=score,
        passed=score >= threshold,
        failure_types=failure_types,
        evidence=_evidence_from(data),
        threshold=threshold,
    )
