"""AI 腔检测：识别 AI 生成文本的常见痕迹，分级输出体检报告。

借鉴 weixin_chat 的 _logic_ai_issues.js 分级质检思路（cliche/connective/pattern/
clickbait 分类 + high/medium/info 分级 + 原文定位），供小说/文案等创作模块
在定稿后自动体检，命中可一键重写。

- cliche    AI 套话（high）：「众所周知/不难发现/值得注意的是…」
- pattern   AI 句式（medium）：「不仅…而且…/让我们共同…」
- connective 机械连接词（medium）：「与此同时/此外/综上所述…」
- clickbait 宣传腔（high）：「不容错过/震撼来袭…」
- filler    空洞修饰（info）：「日益/不断/充分/进一步…」
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 套话（high）：AI 起手式/空转句
_CLICHE = [
    "众所周知", "不难发现", "值得注意的是", "需要注意的是", "总而言之", "综上所述",
    "不可否认", "毋庸置疑", "在这个充满", "在这个快速", "随着时代的", "随着社会",
    "在这个时代", "让我们来", "让我们看看", "我想说", "可以说", "不得不说",
    "毫无疑问", "显而易见", "从某种意义上", "某种程度上",
]
# AI 句式（medium）：结构性机械表达
_PATTERN = [
    "不仅", "而且", "既不是", "也不仅仅是", "让我们共同", "让我们一起", "让我们",
    "正是这种", "正是这些", "或许这就是", "这就是为什么", "这也解释了",
    "与其说", "不如说", "一方面", "另一方面", "归根结底", "说到底",
]
# 机械连接词（medium）：段落衔接的生硬转场
_CONNECTIVE = [
    "与此同时", "此外", "然而", "因此", "所以", "因而", "由此可见", "总的来说",
    "总的来说", "从这个角度", "从这个意义上", "换而言之", "换言之", "值得注意的是",
]
# 宣传腔/标题党（high）
_CLICKBAIT = [
    "不容错过", "惊艳全场", "震撼来袭", "重磅", "干货满满", "必看", "强烈推荐",
    "绝对不要错过", "全网首发", "史诗级", "神作", "封神", "yyds", "YYDS",
]
# 空洞修饰（info）：无信息量形容词/副词
_FILLER = ["日益", "不断", "充分", "进一步", "更加", "愈发", "深深", "真正", "确实"]

_LEVEL_RANK = {"high": 2, "medium": 1, "info": 0}


@dataclass
class AiVoiceIssue:
    """一条 AI 腔命中。"""

    kind: str  # cliche / pattern / connective / clickbait / filler
    level: str  # high / medium / info
    sample: str  # 命中的原文片段
    suggestion: str  # 改写建议

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "level": self.level,
            "sample": self.sample,
            "suggestion": self.suggestion,
        }


_SUGGESTIONS: dict[str, str] = {
    "cliche": "删掉或换成具体事实/场景（AI 套话没有信息量）",
    "pattern": "拆成短句，用具体动作/细节表达（机械句式让读者出戏）",
    "connective": "删掉转场词，用段落本身的逻辑衔接",
    "clickbait": "换成克制的事实陈述（宣传腔伤可信度）",
    "filler": "删掉或换成具体数字/例子（空洞修饰稀释信息）",
}


def check_ai_voice(text: str) -> list[dict[str, str]]:
    """检测文本中的 AI 腔，返回按严重度排序的命中列表（去重）。"""
    if not text:
        return []
    issues: dict[str, AiVoiceIssue] = {}
    for word, kind, level in _all_rules():
        for m in re.finditer(re.escape(word), text):
            start = max(0, m.start() - 8)
            end = min(len(text), m.end() + 8)
            sample = text[start:end].strip().replace("\n", " ")
            key = f"{kind}:{word}"
            if key not in issues:
                issues[key] = AiVoiceIssue(
                    kind=kind,
                    level=level,
                    sample=f"…{sample}…",
                    suggestion=_SUGGESTIONS.get(kind, "换成具体表达"),
                )
            break  # 每个词只报一次
    result = [i.to_dict() for i in issues.values()]
    result.sort(key=lambda x: _LEVEL_RANK.get(x["level"], 0), reverse=True)
    return result


def _all_rules() -> list[tuple[str, str, str]]:
    return (
        [(w, "cliche", "high") for w in _CLICHE]
        + [(w, "pattern", "medium") for w in _PATTERN]
        + [(w, "connective", "medium") for w in _CONNECTIVE]
        + [(w, "clickbait", "high") for w in _CLICKBAIT]
        + [(w, "filler", "info") for w in _FILLER]
    )
