"""Counterfactual Character Test（07 §6）：反事实人物测试 Test A-E。

- A 删除核心情感对象，行为是否仍成立？（情感依赖过重 → 人物降维）
- B 删除主题，行为是否仍成立？（主题依赖）
- C 改变职业，行为是否改变？（职业参与模型）
- D 改变价值层级，行为是否改变？（价值参与模型）
- E 替换关系对象（妻子→父亲→战友→老师），故事是否完全不变？（关系参与模型）

实现：单次 LLM 调用输出 5 个反事实问题的判定（省成本）；JSON 损坏 → 保守失败。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.creative.schemas import CharacterConstitution, CounterfactualResult


@dataclass
class CounterfactualOutcome:
    result: CounterfactualResult
    ok: bool = True  # 是否成功获取判定（JSON 解析成功）
    detail: str = ""

    @property
    def downgraded(self) -> bool:
        """Test A/B 失败 = 人物行为依赖情感/主题对象（降维嫌疑）。"""
        r = self.result
        return (r.drop_emotion_object is False) or (r.drop_theme is False)

    @property
    def generic_character(self) -> bool:
        """Test C/D/E 全不变 = 职业/价值/关系未参与模型（可替换木偶）。"""
        r = self.result
        return (r.change_profession is False
                and r.change_value_hierarchy is False
                and r.substitute_relation is False)

    def as_dict(self) -> dict[str, Any]:
        return {"result": self.result.model_dump(), "ok": self.ok, "detail": self.detail}


def _parse(raw: str) -> CounterfactualResult | None:
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
    if not isinstance(data, dict):
        return None
    try:
        return CounterfactualResult(
            drop_emotion_object=data.get("drop_emotion_object"),
            drop_theme=data.get("drop_theme"),
            change_profession=data.get("change_profession"),
            change_value_hierarchy=data.get("change_value_hierarchy"),
            substitute_relation=data.get("substitute_relation"),
        )
    except Exception:
        return None


async def run_counterfactual_tests(
    provider: Any,
    model: str,
    *,
    behavior: str,
    constitution: CharacterConstitution,
    chapter_context: str = "",
) -> CounterfactualOutcome:
    """执行反事实测试（单次 LLM 调用）。

    behavior：被审查的重大行为；constitution：人物决策模型。
    """
    vh = " > ".join(
        f"{k}({v:.2f})"
        for k, v in sorted(constitution.value_hierarchy.items(), key=lambda kv: -kv[1])
    )
    relations = "、".join(
        f"{r.name}({r.relation},挂载价值:{r.value_link})" for r in constitution.relationships
    ) or "（无）"
    system = (
        "你是反事实叙事评审。对给定人物与行为回答 5 个反事实问题（用直觉与严谨推理）。\n"
        "输出严格 JSON（不要任何多余文字）：\n"
        '{"drop_emotion_object": bool, "drop_theme": bool, '
        '"change_profession": bool, "change_value_hierarchy": bool, '
        '"substitute_relation": bool}\n'
        "语义：\n"
        "- drop_emotion_object=true：删除核心情感对象后行为**仍成立**\n"
        "- drop_theme=true：删除主题后行为**仍成立**\n"
        "- change_profession=true：换职业后行为**会改变**（职业参与模型）\n"
        "- change_value_hierarchy=true：换价值层级后行为**会改变**（价值参与模型）\n"
        "- substitute_relation=true：换关系对象（妻子→父亲/战友/老师）后故事改变\n"
        "若行为完全依赖情感对象/主题，或换职业/价值/关系后故事完全不变，对应项填 false。"
    )
    user = (
        f"【人物】\n身份：{constitution.identity}\n"
        f"价值层级：{vh}\n关系：{relations}\n"
        f"职业信号：{'/'.join(constitution.skills[:5]) or '（未填）'}\n\n"
        f"【被审查的重大行为】\n{behavior}\n\n"
        f"【章节上下文】\n{chapter_context[:1500] or '（未提供）'}\n\n"
        "请输出 5 个反事实问题的 JSON 判定。"
    )
    result = await provider.generate(user, model, system=system, temperature=0.2)
    raw = (getattr(result, "content", "") or "").strip()
    parsed = _parse(raw)
    if parsed is None:
        return CounterfactualOutcome(
            result=CounterfactualResult(), ok=False,
            detail=f"反事实输出非 JSON：{raw[:200]}",
        )
    return CounterfactualOutcome(result=parsed, ok=True)
