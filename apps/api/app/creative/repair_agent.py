"""Repair Agent（08 §8）：按 DiagnosticReport 局部修复，只动被诊断处。

- LLM 部分：把 diagnostic（evidence + repair_strategy）与原文交给修复模型，
  要求局部修复（不重写全文）；P3 接入真实 provider，测试用 fake。
- 确定性部分：locality_check —— 修复 diff 的局部性度量（修复不得大面积重写）。

不变式（08 §1）：
1. Repair 只修被诊断的问题（evidence.text_anchor 定位）
2. 不允许全章重写绕过诊断（diff > 40% 行级差异且非诊断范围 → 拒绝）
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

from app.creative.schemas import DiagnosticReport

# 行级 diff 上限：超过视为"全章重写绕过诊断"
_MAX_DIFF_RATIO = 0.4


@dataclass
class RepairOutcome:
    text: str = ""
    changed: bool = False
    diff_ratio: float = 0.0
    locality_ok: bool = True
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "diff_ratio": round(self.diff_ratio, 3),
            "locality_ok": self.locality_ok,
            "detail": self.detail,
        }


def locality_check(original: str, repaired: str) -> tuple[float, bool]:
    """度量修复局部性：字符级 diff 比例。

    diff_ratio = 变更字符数 / 原文字符数；> _MAX_DIFF_RATIO → 视为全章重写。
    真实章节 800-1500 字：局部修复一段（50 字）≈ 0.03-0.06；全章重写 ≈ 接近 1.0。
    """
    if not original:
        return 0.0, True
    sm = difflib.SequenceMatcher(a=original, b=repaired)
    changed = sum(
        max(len(original[i1:i2]), len(repaired[j1:j2]))
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
        if tag != "equal"
    )
    ratio = changed / len(original)
    return ratio, ratio <= _MAX_DIFF_RATIO


async def repair_chapter_text(
    diagnostic: DiagnosticReport,
    content: str,
    *,
    provider: Any,
    model: str = "",
    max_tokens: int | None = None,
) -> RepairOutcome:
    """按诊断局部修复章节正文。

    provider：OpenAI 兼容文本 provider（generate(prompt, model, system=...)）。
    修复 prompt 携带：失败定位（evidence）、修复策略（repair_strategy）、原文。
    要求：只输出修复后的完整正文；只改被诊断处；不得解释。
    """
    outcome = RepairOutcome(text=content)
    if not content.strip():
        outcome.detail = "原文为空，无法修复"
        return outcome

    evidence_block = "\n".join(
        f"- [{e.text_anchor}] {e.reason}（证据：{e.text[:80]}）"
        for e in diagnostic.evidence[:10]
    )
    strategy_block = "\n".join(
        f"- 回退阶段 {s.stage}：{s.action}" for s in diagnostic.repair_strategy[:5]
    )
    system_prompt = (
        "你是创作系统的修复编辑。按诊断报告对章节做【局部修复】。\n"
        "铁律：\n"
        "- 只修复诊断指出的问题，不得重写全文、不得改动未诊断的内容\n"
        "- 不得改变人物价值/世界规则/时间线（除非诊断明确要求）\n"
        "- 修复必须保持叙事连贯，输出修复后的完整正文（不要解释）\n"
        f"【诊断】指标 {diagnostic.metric.value} 得分 {diagnostic.score:.2f}"
        f"（阈值 {diagnostic.threshold}），失败类型 {diagnostic.failure_type.value}\n"
        f"【证据】\n{evidence_block or '（无）'}\n"
        f"【修复策略】\n{strategy_block or '（按证据就地修复）'}"
    )
    user_prompt = f"【原文】\n{content}\n\n请输出修复后的完整正文："

    try:
        result = await provider.generate(
            user_prompt, model, system=system_prompt, max_tokens=max_tokens
        )
        repaired = (getattr(result, "content", "") or "").strip()
    except Exception as exc:  # pragma: no cover - provider 异常
        outcome.detail = f"修复调用失败：{str(exc)[:200]}"
        return outcome

    if not repaired:
        outcome.detail = "修复模型未返回内容"
        return outcome

    diff_ratio, locality_ok = locality_check(content, repaired)
    outcome.text = repaired
    outcome.changed = repaired != content
    outcome.diff_ratio = diff_ratio
    outcome.locality_ok = locality_ok
    if not locality_ok:
        outcome.detail = (
            f"修复 diff 比例 {diff_ratio:.2f} 超过上限 {_MAX_DIFF_RATIO}："
            "疑似全章重写绕过诊断，拒绝采纳（返回原文）"
        )
        outcome.text = content
        outcome.changed = False
    else:
        outcome.detail = f"局部修复完成（diff {diff_ratio:.2f}）"
    return outcome
