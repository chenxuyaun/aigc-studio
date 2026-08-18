"""Semantic Diversity Engine（07 §7）：防第一联想垄断（确定性部分）。

输入：多个语义方向（每个方向一组关键词/设定钩子）。
输出：方向间平均距离分（0-1）+ 第一联想惩罚建议。

距离定义（纯词表，零 LLM 零 embedding）：
- 方向 A、B 的相似度 = Jaccard(词集A, 词集B)（并集越小越相似）
- 方向间距离 = 1 - 平均 Jaccard
- Semantic Diversity Score = 平均距离（≥0.5 视为足够多样；<0.3 触发第一联想警告）

LLM 部分（Semantic Explorer 生成方向）在 P2 接入；本模块只做确定性度量与判定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SemanticDirection:
    """一个语义方向：id + 关键词集 + 钩子说明。"""

    id: str
    keywords: list[str]
    hook: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "keywords": self.keywords, "hook": self.hook}


@dataclass
class DiversityVerdict:
    score: float = 0.0
    threshold: float = 0.7
    directions: list[SemanticDirection] = field(default_factory=list)
    similar_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    first_association: bool = False
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.score >= self.threshold

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "threshold": self.threshold,
            "passed": self.passed,
            "first_association": self.first_association,
            "similar_pairs": [
                {"a": a, "b": b, "similarity": round(s, 3)} for a, b, s in self.similar_pairs
            ],
            "detail": self.detail,
        }


def _similarity(a: list[str], b: list[str]) -> float:
    """方向相似度 = max(共享词比例, 共享字符比例)。

    - 共享词比例：|A∩B| / min(|A|,|B|)（对方向大小敏感，识别词面重叠）
    - 共享字符比例：字符集重叠 / 较小字符集（识别近义字面，如 旧桥 vs 桥）
    两个视角取强，避免"词不同但语义同簇"（第一联想特征）漏检。
    """
    wa, wb = set(a), set(b)
    word_sim = len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0
    ca = set("".join(a))
    cb = set("".join(b))
    char_sim = len(ca & cb) / min(len(ca), len(cb)) if ca and cb else 0.0
    return max(word_sim, char_sim)


def diversity_score(directions: list[SemanticDirection], *, threshold: float = 0.7,
                    similar_sim: float = 0.5) -> DiversityVerdict:
    """评估语义方向多样性。directions < 2 时无法评估（score=0，passed=False）。

    - score = 1 - 平均方向相似度（方向间平均距离）
    - passed：score >= threshold
    - first_association：存在高相似方向对 且 平均距离不足（同簇聚集 = 第一联想嫌疑）
    """
    verdict = DiversityVerdict(threshold=threshold, directions=directions)
    if len(directions) < 2:
        verdict.detail = f"语义方向不足（{len(directions)} < 2）：无法评估多样性"
        return verdict

    sims: list[float] = []
    for i in range(len(directions)):
        for j in range(i + 1, len(directions)):
            sim = _similarity(directions[i].keywords, directions[j].keywords)
            sims.append(sim)
            if sim > similar_sim:
                verdict.similar_pairs.append((directions[i].id, directions[j].id, sim))

    verdict.score = 1.0 - (sum(sims) / len(sims) if sims else 0.0)

    if verdict.similar_pairs and verdict.score < threshold:
        verdict.first_association = True
        verdict.detail = (
            f"语义多样性不足（score={verdict.score:.2f} < {threshold}）："
            f"{len(verdict.similar_pairs)} 对方向高度相似，疑似第一联想垄断"
            "（如 烟雨→江南/油纸伞/青石板 同质簇）"
        )
    elif verdict.score < threshold:
        verdict.detail = (
            f"多样性偏低（score={verdict.score:.2f} < {threshold}）：建议扩展跨域方向"
        )
    else:
        verdict.detail = f"语义多样性达标（score={verdict.score:.2f} ≥ {threshold}）"
    return verdict


# 示例（07 §7）：第一联想簇 vs 跨域方向
# 第一联想簇：方向字面同簇（烟雨/雨巷/青石板/江南 反复出现）——正是 AI 的第一联想
EXAMPLE_FIRST_ASSOCIATION = [
    SemanticDirection("江南", ["江南", "烟雨", "油纸伞", "青石板", "雨巷"]),
    SemanticDirection("雨巷", ["烟雨", "雨巷", "故人", "离愁", "青石板"]),
    SemanticDirection("水乡", ["烟雨", "水乡", "小船", "青石板", "旧桥"]),
]
EXAMPLE_CROSS_DOMAIN = [
    SemanticDirection("城市排水", ["排水", "管网", "内涝", "泵站", "雨污分流"]),
    SemanticDirection("铁路调度", ["铁路", "限速", "调度", "信号", "防汛"]),
    SemanticDirection("工程检测", ["桥梁", "伸缩缝", "病害", "复检", "荷载"]),
]


