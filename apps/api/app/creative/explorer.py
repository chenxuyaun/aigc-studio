"""Semantic Explorer（07 §7 + P1-6）：主题 → 多语义方向扩展，防第一联想垄断。

流程：
1. LLM 生成 ≥3 个语义方向（自然/工业/工程/医学/交通…跨域）
2. 确定性 diversity_score 校验（semantic_diversity.py）
3. score 不达标 → 要求模型重构（跨域重试，最多 2 次）

LLM 部分 P3 接真实 provider；测试用 fake。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.creative.semantic_diversity import (
    DiversityVerdict,
    SemanticDirection,
    diversity_score,
)

_EXPLORER_SYSTEM = (
    "你是语义扩展策划。给定创作主题，输出多个【彼此远离】的语义方向，"
    "避免第一联想垄断（如 烟雨→江南/油纸伞/青石板 这种同质簇是反例）。\n"
    "要求：\n"
    "- 生成 {n} 个方向，覆盖不同领域（如 自然/城市/工业/农业/工程/医学/交通/科技/法律/劳动…）\n"
    "- 每个方向：id（2-4 字）+ keywords（5-8 个领域关键词，与主题交叉）"
    "+ hook（30 字内设定钩子）\n"
    "- 优先寻找「主题 × 人物 × 职业 × 世界」的独特交叉点，拒绝猎奇式替代\n"
    "输出严格 JSON（不要任何多余文字）：\n"
    '{{"directions": [{{"id": "城市排水", "keywords": ["排水","管网","内涝","泵站","雨污分流"], '
    '"hook": "梅雨导致铁路限速，排水工程师连夜值守"}}]}}'
)


def _parse_directions(raw: str) -> list[SemanticDirection] | None:
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if 0 <= start < end:
            try:
                data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    items = (data or {}).get("directions") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return None
    out: list[SemanticDirection] = []
    for it in items[:5]:
        if isinstance(it, dict) and it.get("keywords"):
            out.append(
                SemanticDirection(
                    id=str(it.get("id") or "方向")[:10],
                    keywords=[str(k)[:20] for k in it["keywords"][:8]],
                    hook=str(it.get("hook") or "")[:120],
                )
            )
    return out or None


async def explore_semantic_directions(
    provider: Any,
    model: str,
    theme: str,
    *,
    n_directions: int = 3,
    max_retries: int = 2,
    diversity_threshold: float = 0.7,
) -> tuple[list[SemanticDirection] | None, DiversityVerdict | None, str]:
    """主题 → 语义方向（LLM）+ 多样性校验（确定性）。

    返回 (directions, verdict, detail)；directions=None = 探索失败。
    """
    system = _EXPLORER_SYSTEM.format(n=n_directions)
    user = f"创作主题：{theme}\n\n请输出 {n_directions} 个语义方向的 JSON。"
    last_raw = ""
    last_detail = ""
    directions: list[SemanticDirection] | None = None
    verdict: DiversityVerdict | None = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            user = (
                f"创作主题：{theme}\n\n"
                f"上一版语义多样性不足（{last_detail}）。"
                f"请换到更远的领域重新生成 {n_directions} 个方向的 JSON。"
            )
        result = await provider.generate(user, model, system=system, temperature=0.7)
        last_raw = (getattr(result, "content", "") or "").strip()
        directions = _parse_directions(last_raw)
        if not directions or len(directions) < 2:
            continue
        verdict = diversity_score(directions, threshold=diversity_threshold)
        last_detail = verdict.detail
        if verdict.passed:
            return directions, verdict, f"语义探索成功：{verdict.detail}"
    # 重试耗尽
    if not directions:
        return None, None, f"语义探索失败（输出非 JSON）：{last_raw[:200]}"
    assert verdict is not None  # directions 非空时 verdict 必已赋值
    return directions, verdict, f"多样性未达标（重试耗尽）：{verdict.detail}"
