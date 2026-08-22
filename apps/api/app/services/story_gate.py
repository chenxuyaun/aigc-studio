"""创作内核接入层（P3-1）：generate_chapter 的 draft_mode 灰度。

流程（08 §1 + 06 §5 落点）：
1. 生成草稿（不直接落库 done）
2. 确定性预检（零 LLM）：情绪捷径 + CVI 启发式（若人物已建模）
3. L0 LLM Critic 门（CVI/CAI/CCI/WCI，独立视角）
4. PASS → done + CreativeQualityReport 存 notes；FAIL → Repair → 再验证
5. 修复预算耗尽 → status=review（HUMAN_REVIEW_REQUIRED），正文不落库

灰度：story_forge.generate_chapter(draft_mode=None) → 由 settings.CREATIVE_ENGINE_ENABLED 决定；
draft_mode=False 走 legacy（完全不变）。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.creative.cliche_detector import detect_shortcuts
from app.creative.critics.cvi_precheck import assess_behavior_motivation
from app.creative.critics.llm import cai_critic, cci_critic, cvi_critic, wci_critic
from app.creative.pipeline import CriticVerdict
from app.creative.repair_agent import repair_chapter_text
from app.creative.schemas import (
    CharacterConstitution,
    CreativeQualityReport,
    GateVerdict,
    MetricName,
    QualityIssue,
)
from app.creative.store import constitution_to_bible_block, get_constitution


async def deterministic_quality_report(
    db: AsyncSession,
    project: Any,
    content: str,
    chapter: Any,
) -> dict[str, Any] | None:
    """确定性质量预检（P3-5，零 LLM）：情绪捷径 + CVI 启发式 → 轻量 QualityReport。

    供流式生成端点调用（流式场景不跑 LLM Critic，仅确定性指标）；
    结果存 chapter.notes["quality_report"] 并返回 dict。
    """
    issues: list[QualityIssue] = []
    shortcut = detect_shortcuts(content)
    if shortcut.level >= 2:
        issues.append(QualityIssue(level="major", text=f"情绪捷径：{shortcut.detail}"))
    try:
        constitutions = await _load_constitutions(db, project)
    except Exception:
        constitutions = {}
    for name, c in constitutions.items():
        for behavior in _extract_behaviors(content):
            pre = assess_behavior_motivation(behavior, c)
            if not pre.ok and pre.failure_type is not None:
                issues.append(
                    QualityIssue(
                        level="critical",
                        text=f"【{name}】{pre.detail}（行为：{behavior[:50]}）",
                    )
                )
                break  # 每人最多一条
    has_critical = any(i.level == "critical" for i in issues)
    report = CreativeQualityReport(
        character_value_integrity=0.0, character_agency=0.0,
        causal_integrity=0.0, world_consistency=0.0,
        semantic_diversity=0.0, narrative_diversity=0.0,
        emotional_authenticity=0.0, theme_emergence=0.0,
        cliche_risk=min(1.0, shortcut.level / 3.0), style_risk=0.0,
        critical_issues=[i for i in issues if i.level == "critical"],
        major_issues=[i for i in issues if i.level == "major"],
        minor_issues=[i for i in issues if i.level == "minor"],
        final_status=(
            GateVerdict.REVIEW_REQUIRED if has_critical else GateVerdict.PASS
        ),
    )
    payload = report.model_dump()
    try:
        notes = (
            json.loads(chapter.notes) if isinstance(chapter.notes, str) and chapter.notes else {}
        )
        notes["quality_report"] = payload
        chapter.notes = json.dumps(notes, ensure_ascii=False)
    except Exception:
        pass
    return payload

# 确定性预检的"重大行为"提取：含行为动词的句子（简化启发式）
_BEHAVIOR_MARKERS = ("他", "她", "决定", "选择", "拒绝", "离开", "放弃", "没有", "答应", "承诺")


async def _load_constitutions(
    db: AsyncSession, project: Any
) -> dict[str, CharacterConstitution]:
    """加载项目角色实例的 Constitution（未建模 → 跳过）。

    以 constitution 是否已建模为准（不依赖 character_asset_id——
    纯文字占位角色也可有决策模型）。
    """
    from app.services.story_forge import list_story_characters

    out: dict[str, CharacterConstitution] = {}
    chars = await list_story_characters(db, str(project.user_id), str(project.id))
    for s in chars:
        c = await get_constitution(db, str(s["id"]))
        if c is not None:
            out[str(s["name"])] = c
    return out


def _extract_behaviors(text: str, max_items: int = 5) -> list[str]:
    """从正文提取疑似重大行为句（启发式：含人物指代 + 行为标记）。

    行为句携带其后一句上下文——动机解释（价值/情境）常在行为句之后，
    单独评估行为句会漏掉价值信号（如「他没去剪彩。复检数据出来了」）。
    """
    sentences = [s.strip() for s in (text or "").split("。") if s.strip()]
    out: list[str] = []
    for i, line in enumerate(sentences):
        if any(m in line for m in _BEHAVIOR_MARKERS):
            merged = line
            if i + 1 < len(sentences):
                merged += "。" + sentences[i + 1]
            out.append(merged[:300])
        if len(out) >= max_items:
            break
    return out


async def run_gated_generation(
    db: AsyncSession,
    *,
    user_id: str,
    project: Any,
    chapter: Any,
    provider: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """执行带质量门的章节生成。返回：
    {content, status: done|review, quality_report, diagnostics, repair_history}
    """
    max_rounds = max(1, int(getattr(settings, "CREATIVE_MAX_REPAIR_ROUNDS", 2) or 2))

    # ① 生成草稿（与 legacy 同一调用形态）
    try:
        result = await provider.generate(
            user_prompt, model, system=system_prompt,
            temperature=temperature, max_tokens=max_tokens,
        )
        content = (result.content or "").strip()
    except Exception as exc:
        return {"error": f"生成失败：{str(exc)[:200]}"}
    if not content:
        return {"error": "模型未返回内容"}

    # ② Constitution（CVI 依据）
    constitutions = await _load_constitutions(db, project)
    constitution_block = "\n\n".join(
        constitution_to_bible_block(c, name) for name, c in constitutions.items()
    )

    # ③ 确定性预检（零 LLM）
    issues: list[QualityIssue] = []
    shortcut = detect_shortcuts(content)
    if shortcut.level >= 2:
        issues.append(
            QualityIssue(level="major", text=f"情绪捷径：{shortcut.detail}")
        )
    for name, c in constitutions.items():
        for behavior in _extract_behaviors(content):
            pre = assess_behavior_motivation(behavior, c)
            if not pre.ok and pre.failure_type is not None:
                issues.append(
                    QualityIssue(
                        level="critical",
                        text=f"【{name}】{pre.detail}（行为：{behavior[:60]}）",
                    )
                )
                break  # 每人最多报一条

    # ④ L0 LLM Critic 门
    async def _run_critics(text: str) -> list[CriticVerdict]:
        return await asyncio_gather_safe([
            (cvi_critic(provider, model, text, constitution_block), MetricName.CVI),
            (cai_critic(provider, model, text), MetricName.CAI),
            (cci_critic(provider, model, text), MetricName.CCI),
            (wci_critic(provider, model, text), MetricName.WCI),
        ])

    verdicts = await _run_critics(content)
    # 确定性预检的 critical 问题直接视为 CVI FAIL（不靠 LLM 兜底）
    if any(i.level == "critical" for i in issues):
        verdicts = [
            v if v.metric is not MetricName.CVI else CriticVerdict(
                MetricName.CVI, min(v.score, 0.4), 0.85, False,
                failure_type=None, evidence=v.evidence,
            )
            for v in verdicts
        ]

    repair_history: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    failed = [v for v in verdicts if not v.passed]
    if failed:
        for rnd in range(1, max_rounds + 1):
            primary = failed[0]
            diagnostic = primary.to_diagnostic(
                int(chapter.chapter_no or 0), retry_used=rnd, retry_max=max_rounds
            )
            diagnostics.append(diagnostic.model_dump())
            outcome = await repair_chapter_text(
                diagnostic, content, provider=provider, model=model
            )
            if not outcome.changed:
                repair_history.append(
                    {"round": rnd, "issue": f"{primary.metric.value}", "fixed": False}
                )
                break
            content = outcome.text
            repair_history.append(
                {"round": rnd, "issue": f"{primary.metric.value}", "fixed": False}
            )
            verdicts = await _run_critics(content)
            failed = [v for v in verdicts if not v.passed]
            if not failed:
                repair_history[-1]["fixed"] = True
                break

    passed = not failed
    final_status = GateVerdict.PASS if passed else GateVerdict.REVIEW_REQUIRED
    if passed:
        for v in verdicts:
            if not v.passed:
                final_status = GateVerdict.REVIEW_REQUIRED
                passed = False
                break

    by_metric = {v.metric: v for v in verdicts}
    report = CreativeQualityReport(
        character_value_integrity=by_metric.get(MetricName.CVI, CriticVerdict(
            MetricName.CVI, 0.0, 0.85, False)).score,
        character_agency=by_metric.get(MetricName.CAI, CriticVerdict(
            MetricName.CAI, 0.0, 0.85, False)).score,
        causal_integrity=by_metric.get(MetricName.CCI, CriticVerdict(
            MetricName.CCI, 0.0, 0.85, False)).score,
        world_consistency=by_metric.get(MetricName.WCI, CriticVerdict(
            MetricName.WCI, 0.0, 0.9, False)).score,
        semantic_diversity=0.0, narrative_diversity=0.0,
        emotional_authenticity=0.0, theme_emergence=0.0,
        cliche_risk=min(1.0, shortcut.level / 3.0),
        style_risk=0.0,
        critical_issues=[i for i in issues if i.level == "critical"],
        major_issues=[i for i in issues if i.level == "major"],
        minor_issues=[i for i in issues if i.level == "minor"],
        repair_history=repair_history,
        final_status=final_status,
    )

    return {
        "content": content,
        "status": "done" if passed else "review",
        "quality_report": report.model_dump(),
        "diagnostics": diagnostics,
        "repair_history": repair_history,
    }


async def asyncio_gather_safe(coros: list[tuple[Any, MetricName]]) -> list[CriticVerdict]:
    """并行执行 critic 调用（异常隔离：单 critic 失败 → 该 metric 保守 FAIL）。"""
    import asyncio

    from app.creative.schemas import DiagnosticEvidence, FailureType

    async def _safe(pair: tuple[Any, MetricName]) -> CriticVerdict:
        coro, metric = pair
        try:
            return await coro
        except Exception as exc:  # pragma: no cover - provider 异常
            return CriticVerdict(
                metric, 0.0, 0.85, False,
                failure_type=FailureType.MISSING_MOTIVATION,
                evidence=[DiagnosticEvidence(text=str(exc)[:200], text_anchor="critic-exc",
                                             reason="critic 调用异常")],
            )

    return await asyncio.gather(*[_safe(p) for p in coros])
