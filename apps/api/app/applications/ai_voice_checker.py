"""AI 腔检测：识别 AI 生成文本的常见痕迹，分级输出体检报告。

借鉴 weixin_chat 的 _logic_ai_issues.js 分级质检思路（cliche/connective/pattern/
clickbait 分类 + high/medium/info 分级 + 原文定位），供小说/文案等创作模块
在定稿后自动体检，命中可一键重写。

- cliche    AI 套话（high）：「众所周知/不难发现/值得注意的是…」
- pattern   AI 句式（medium）：「不仅…而且…/让我们共同…」
- connective 机械连接词（medium）：「与此同时/此外/综上所述…」
- clickbait 宣传腔（high）：「不容错过/震撼来袭…」
- filler    空洞修饰（info）：「日益/不断/充分/进一步…」

Personal Voice Engine 扩展：传入 voice_dna（用户文风档案）时追加两类命中——
- voice_avoid：文本出现用户**明确忌讳**的表达（档案 avoid 列表，非通用禁词表）
- voice_rhythm：用户偏好短句但文本通篇长句（档案 sentence_length=short）
这使检测从「通用 AI 腔」升级为「对照具体用户的写作习惯」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 套话（high）：AI 起手式/空转句
_CLICHE = [
    "众所周知",
    "不难发现",
    "值得注意的是",
    "需要注意的是",
    "总而言之",
    "综上所述",
    "不可否认",
    "毋庸置疑",
    "在这个充满",
    "在这个快速",
    "随着时代的",
    "随着社会",
    "在这个时代",
    "让我们来",
    "让我们看看",
    "我想说",
    "可以说",
    "不得不说",
    "毫无疑问",
    "显而易见",
    "从某种意义上",
    "某种程度上",
]
# AI 句式（medium）：结构性机械表达
_PATTERN = [
    "不仅",
    "而且",
    "既不是",
    "也不仅仅是",
    "让我们共同",
    "让我们一起",
    "让我们",
    "正是这种",
    "正是这些",
    "或许这就是",
    "这就是为什么",
    "这也解释了",
    "与其说",
    "不如说",
    "一方面",
    "另一方面",
    "归根结底",
    "说到底",
]
# 机械连接词（medium）：段落衔接的生硬转场
_CONNECTIVE = [
    "与此同时",
    "此外",
    "然而",
    "因此",
    "所以",
    "因而",
    "由此可见",
    "总的来说",
    "总的来说",
    "从这个角度",
    "从这个意义上",
    "换而言之",
    "换言之",
    "值得注意的是",
]
# 宣传腔/标题党（high）
_CLICKBAIT = [
    "不容错过",
    "惊艳全场",
    "震撼来袭",
    "重磅",
    "干货满满",
    "必看",
    "强烈推荐",
    "绝对不要错过",
    "全网首发",
    "史诗级",
    "神作",
    "封神",
    "yyds",
    "YYDS",
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


def check_ai_voice(
    text: str, voice_dna: dict | None = None
) -> list[dict[str, str]]:
    """检测文本中的 AI 腔，返回按严重度排序的命中列表（去重）。

    voice_dna（可选）：用户文风档案（voice_profiles.voice_dna），
    提供时追加「个人忌讳表达 / 节奏偏好不符」两类命中；None 退化为通用规则。
    """
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

    # Personal Voice：对照用户自己的文风档案补查（不替代通用规则）
    if isinstance(voice_dna, dict):
        for issue in _voice_against_dna(text, voice_dna):
            key = f"{issue.kind}:{issue.sample[:20]}"
            if key not in issues:
                issues[key] = issue

    result = [i.to_dict() for i in issues.values()]
    result.sort(key=lambda x: _LEVEL_RANK.get(x["level"], 0), reverse=True)
    return result


def _voice_against_dna(text: str, dna: dict) -> list[AiVoiceIssue]:
    """对照用户文风档案查「个人忌讳 + 节奏偏好」。"""
    out: list[AiVoiceIssue] = []
    # ① 忌讳表达：用户明确 avoid 的词/腔调，出现即命中（≥2 字防误报）
    for w in (dna.get("avoid") or [])[:20]:
        word = str(w).strip()
        if len(word) < 2:
            continue
        for m in re.finditer(re.escape(word), text):
            start = max(0, m.start() - 8)
            end = min(len(text), m.end() + 8)
            out.append(
                AiVoiceIssue(
                    kind="voice_avoid",
                    level="high",
                    sample=f"…{text[start:end].strip().replace(chr(10), ' ')}…",
                    suggestion=f"这是你文风档案里忌讳的表达（「{word}」），删掉或换自己的说法",
                )
            )
            break  # 每个词只报一次
    # ② 节奏偏好：档案写 short（喜欢短句）却通篇长句
    if str(dna.get("sentence_length") or "") == "short":
        sents = [s for s in re.split(r"[。！？!?…\n]", text) if len(s.strip()) >= 2]
        long_ones = [s.strip() for s in sents if len(s.strip()) > 30]
        if long_ones and len(long_ones) / max(len(sents), 1) >= 0.5:
            sample = long_ones[0][:40]
            out.append(
                AiVoiceIssue(
                    kind="voice_rhythm",
                    level="medium",
                    sample=f"…{sample}…",
                    suggestion="你的文风档案偏好短句，这句超过 30 字，试着拆成两句",
                )
            )
    return out


def _all_rules() -> list[tuple[str, str, str]]:
    return (
        [(w, "cliche", "high") for w in _CLICHE]
        + [(w, "pattern", "medium") for w in _PATTERN]
        + [(w, "connective", "medium") for w in _CONNECTIVE]
        + [(w, "clickbait", "high") for w in _CLICKBAIT]
        + [(w, "filler", "info") for w in _FILLER]
    )
