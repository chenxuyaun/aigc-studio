"""Emotional Shortcut Detector（07 §5）：确定性检测 AI 高频情绪捷径。

规则（不是禁止，是"替代验证"）：
- level-1 RENDER_ONLY：套路元素出现但未与人物价值/历史/行动绑定（渲染 > 参与）
- level-2 CLICHÉ_CLUSTER：一次命中 ≥3 个不同套路元素（套路组合拳）
- level-3 启发式 SHORTCUT_AS_DEPTH：全文套路元素多且人物维度词（价值/职业/决策）少
  → 套路正在替代人物深度（需 LLM Critic 确认，本模块只给证据）

纯函数，零 LLM 成本；输入章节正文，输出结构化命中。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.creative.schemas import EMOTIONAL_SHORTCUT_LEXICON

# 人物深度维度词（价值/职业/决策参与叙事的信号）。命中这些词说明人物维度在场。
_DEPTH_SIGNAL_WORDS: tuple[str, ...] = (
    # 价值/职业/决策类
    "责任", "义务", "使命", "职责", "职业", "工程师", "医生", "法官", "教师",
    "决定", "选择", "权衡", "标准", "原则", "底线", "规程", "流程", "验收",
    "报告", "检查", "数据", "复检", "隐患", "安全", "伦理", "承诺",
    "签字", "桥墩", "记录", "审查", "复核", "巡检", "维修", "施工", "设计",
    # 关系/冲突参与
    "冲突", "矛盾", "两难", "代价", "取舍",
)

# 深度信号词条数阈值：≥2 视为人物维度在场
_DEPTH_SIGNAL_THRESHOLD = 2
# 集群阈值：一次命中 ≥3 个不同套路词 = 套路组合拳
_CLUSTER_THRESHOLD = 3


@dataclass
class ShortcutHit:
    term: str
    count: int


@dataclass
class ShortcutReport:
    text: str = ""
    hits: list[ShortcutHit] = field(default_factory=list)
    depth_signal_count: int = 0
    cluster: bool = False
    render_only: bool = False
    shortcut_as_depth: bool = False
    level: int = 0  # 0=clean 1=RENDER_ONLY 2=CLICHÉ_CLUSTER 3=SHORTCUT_AS_DEPTH
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "hits": [{"term": h.term, "count": h.count} for h in self.hits],
            "depth_signal_count": self.depth_signal_count,
            "cluster": self.cluster,
            "render_only": self.render_only,
            "shortcut_as_depth": self.shortcut_as_depth,
            "level": self.level,
            "detail": self.detail,
        }


def detect_shortcuts(text: str, *, cluster_threshold: int = _CLUSTER_THRESHOLD) -> ShortcutReport:
    """检测正文中的情绪捷径元素。text 为空返回空报告。"""
    report = ShortcutReport(text=text)
    if not text:
        return report

    hits: list[ShortcutHit] = []
    for term in EMOTIONAL_SHORTCUT_LEXICON:
        c = text.count(term)
        if c > 0:
            hits.append(ShortcutHit(term=term, count=c))
    if not hits:
        return report
    report.hits = hits

    report.depth_signal_count = sum(1 for w in _DEPTH_SIGNAL_WORDS if w in text)
    report.cluster = len(hits) >= cluster_threshold

    # level 判定
    if report.depth_signal_count < _DEPTH_SIGNAL_THRESHOLD:
        # 套路元素在场但人物维度缺席 → 套路正在替代深度
        report.shortcut_as_depth = True
        report.level = 3
        report.detail = (
            f"命中 {len(hits)} 个套路元素但人物维度词仅 {report.depth_signal_count} 个"
            f"（<{_DEPTH_SIGNAL_THRESHOLD}）：套路可能在替代人物深度，需 CVI 确认"
        )
    elif report.cluster:
        report.level = 2
        report.detail = f"套路组合拳：一次命中 {len(hits)} 个不同套路元素（≥{cluster_threshold}）"
    else:
        report.level = 1
        report.render_only = True
        report.detail = "套路元素出现但人物维度在场：需确认其是否真正参与叙事（渲染 > 参与）"

    return report


