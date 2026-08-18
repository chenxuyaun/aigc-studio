"""创作流水线编排（08）：Generate → Extract → Check → Critic → Diagnose → Repair → Revalidate。

所有步骤为可注入接口（writer/critics/repair_agent 由调用方提供）：
- P3 接入时：writer=Scene Writer（LLM）、critics=LLM 检查器、repair_agent=Repair Agent
- 测试时：全部用确定性 fake 实现，验证流程分支

流程（08 §1）：
① Generate → ② Extract State → ③ Deterministic Check（零 LLM，FAIL 直接诊断）
④ Critic（L0）→ PASS → ⑤ 输出 QualityReport；FAIL → ⑥ Diagnostic → ⑦/⑧ Repair → ④ 重验
⑨ retry 预算耗尽 → HUMAN_REVIEW_REQUIRED（绝不允许无限重生成）
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.creative.diagnostic import make_diagnostic
from app.creative.schemas import (
    CreativeQualityReport,
    DiagnosticEvidence,
    DiagnosticReport,
    FailureType,
    GateVerdict,
    MetricName,
    RepairHistoryEntry,
    StateDelta,
)

# 各 Critic 的输入输出契约
WriterFn = Callable[[], Awaitable[tuple[str, StateDelta]]]
ExtractFn = Callable[[str], Awaitable[StateDelta]]
DeterministicFn = Callable[[StateDelta], Awaitable[list[str]]]
RepairFn = Callable[[DiagnosticReport, str], Awaitable[tuple[str, bool]]]


@dataclass
class CriticVerdict:
    metric: MetricName
    score: float
    threshold: float
    passed: bool
    failure_type: FailureType | None = None
    evidence: list[DiagnosticEvidence] = field(default_factory=list)

    def to_diagnostic(self, chapter_no: int, retry_used: int, retry_max: int) -> DiagnosticReport:
        return make_diagnostic(
            metric=self.metric,
            score=self.score,
            threshold=self.threshold,
            failure_type=self.failure_type or FailureType.MISSING_MOTIVATION,
            chapter_no=chapter_no,
            evidence=self.evidence,
            retry_used=retry_used,
            retry_max=retry_max,
        )


CriticFn = Callable[[str, StateDelta], Awaitable[CriticVerdict]]


@dataclass
class PipelineConfig:
    max_repair_rounds: int = 2
    l0_thresholds: dict[MetricName, float] = field(
        default_factory=lambda: {
            MetricName.CVI: 0.85,
            MetricName.CAI: 0.85,
            MetricName.CCI: 0.85,
            MetricName.WCI: 0.90,
        }
    )


@dataclass
class PipelineResult:
    status: GateVerdict
    content: str = ""
    quality_report: CreativeQualityReport | None = None
    diagnostics: list[DiagnosticReport] = field(default_factory=list)
    repair_history: list[RepairHistoryEntry] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status is GateVerdict.PASS


async def run_creative_pipeline(
    *,
    writer: WriterFn,
    extract_state: ExtractFn,
    deterministic_check: DeterministicFn,
    critics: list[CriticFn],
    repair_agent: RepairFn,
    config: PipelineConfig | None = None,
    chapter_no: int = 0,
) -> PipelineResult:
    """执行完整创作流水线。返回 PASS / REJECT / HUMAN_REVIEW_REQUIRED。"""
    cfg = config or PipelineConfig()
    content: str = ""
    diagnostics: list[DiagnosticReport] = []
    repair_history: list[RepairHistoryEntry] = []

    async def _evaluate(text: str) -> tuple[StateDelta, list[CriticVerdict], list[str]]:
        delta = await extract_state(text)
        problems = await deterministic_check(delta)
        if problems:
            return delta, [], problems
        verdicts = await asyncio.gather(*(c(text, delta) for c in critics))
        return delta, list(verdicts), []

    # ① 生成草稿
    content, _delta = await writer()

    # ②③④ 首轮验证
    _delta, verdicts, det_problems = await _evaluate(content)

    # 确定性 FAIL：直接诊断，不进 LLM Critic
    if det_problems:
        diagnostics.append(
            DiagnosticReport(
                status=GateVerdict.REJECT,
                metric=MetricName.WCI,
                score=0.0,
                threshold=0.9,
                failure_type=FailureType.TIMELINE_CONFLICT,
                chapter_no=chapter_no,
                evidence=[
                    DiagnosticEvidence(text=p, text_anchor="state", reason="确定性检查")
                    for p in det_problems[:10]
                ],
                repair_strategy=[],
            )
        )
        return PipelineResult(
            status=GateVerdict.REJECT, content=content,
            diagnostics=diagnostics, repair_history=repair_history,
        )

    # ④ L0 Critic 门
    failed = [v for v in verdicts if not v.passed]
    if not failed:
        return PipelineResult(
            status=GateVerdict.PASS, content=content,
            quality_report=_quality_report_from(verdicts, []),
            diagnostics=diagnostics, repair_history=repair_history,
        )

    # ⑥⑦⑧ 修复循环
    for rnd in range(1, cfg.max_repair_rounds + 1):
        primary = failed[0]
        diagnostic = primary.to_diagnostic(
            chapter_no, retry_used=rnd, retry_max=cfg.max_repair_rounds
        )
        diagnostics.append(diagnostic)
        content, changed = await repair_agent(diagnostic, content)
        if not changed:
            break
        issue = f"{primary.metric.value}:{primary.failure_type}"
        repair_history.append(RepairHistoryEntry(round=rnd, issue=issue, fixed=False))
        # 再验证
        _delta, verdicts, det_problems = await _evaluate(content)
        if det_problems:
            continue
        failed = [v for v in verdicts if not v.passed]
        if not failed:
            repair_history[-1].fixed = True
            return PipelineResult(
                status=GateVerdict.PASS, content=content,
                quality_report=_quality_report_from(verdicts, repair_history),
                diagnostics=diagnostics, repair_history=repair_history,
            )

    # ⑨ 预算耗尽 → 人工
    return PipelineResult(
        status=GateVerdict.REVIEW_REQUIRED, content=content,
        diagnostics=diagnostics, repair_history=repair_history,
    )


def _quality_report_from(
    verdicts: list[CriticVerdict], repair_history: list[RepairHistoryEntry]
) -> CreativeQualityReport:
    """Critic 判定 → Creative Quality Report（L0 指标；L1-L3 留 P2 软门填充）。"""
    by_metric = {v.metric: v for v in verdicts}
    return CreativeQualityReport(
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
        cliche_risk=0.0, style_risk=0.0,
        repair_history=repair_history,
        final_status=GateVerdict.PASS,
    )

