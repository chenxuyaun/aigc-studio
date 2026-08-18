"""Style Firewall（07 §8）：校验 Style Agent 的改动只落在 FLEXIBLE 层。

确定性规则（零 LLM）：
1. 事实指纹提取：数字 / 时间词 / 传入术语表（人物名/地名/关键物）出现集合
2. 变体不得删除原文事实指纹（删 = 改事实）
3. 变体新增未在术语表内的未知术语 → 提示（疑似注入新事实）
4. 仅句式/措辞变化（指纹一致）→ ACCEPT

Style Agent 的权限 = 语言/节奏/句式/意象/修辞/叙述声音；本校验器是其物理边界。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 事实指纹类别（FLEXIBLE 层不得触碰的文本信号）
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
# 常见时间词（日期/时刻/年份——时间线 IMMUTABLE 的文本信号）
_TIME_WORDS = (
    "今天", "昨天", "明天", "上周", "下周", "去年", "今年", "明年",
    "早晨", "中午", "傍晚", "深夜", "凌晨", "通车日", "剪彩日", "婚礼", "葬礼",
)


@dataclass
class StyleDiffVerdict:
    accepted: bool = True
    removed_numbers: list[str] = field(default_factory=list)
    removed_terms: list[str] = field(default_factory=list)
    added_unknown_terms: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "removed_numbers": self.removed_numbers,
            "removed_terms": self.removed_terms,
            "added_unknown_terms": self.added_unknown_terms,
            "detail": self.detail,
        }


def _fingerprint(text: str, terms: tuple[str, ...]) -> tuple[set[str], set[str], set[str]]:
    numbers = set(_NUMBER_RE.findall(text))
    times = {w for w in _TIME_WORDS if w in text}
    terms_hit = {t for t in terms if t in text}
    return numbers, times, terms_hit


def check_style_delta(
    original: str,
    variant: str,
    *,
    terms: tuple[str, ...] = (),
) -> StyleDiffVerdict:
    """校验风格变体是否越权修改故事事实。

    terms：故事术语表（人物名/地名/关键物/价值词）。不传时仅做数字与时间词检查。
    """
    verdict = StyleDiffVerdict()
    if not original or not variant:
        verdict.accepted = False
        verdict.detail = "原文或变体为空"
        return verdict

    o_nums, o_times, o_terms = _fingerprint(original, terms)
    v_nums, v_times, v_terms = _fingerprint(variant, terms)

    # 1) 数字不得被删除（事实/时间数值）
    verdict.removed_numbers = sorted(o_nums - v_nums)
    # 2) 时间词不得被删除（时间线锚点）
    removed_times = sorted(o_times - v_times)
    verdict.removed_terms.extend(removed_times)
    # 3) 术语表命中不得被删除（人物/地点/关键物/价值词）
    verdict.removed_terms.extend(sorted(o_terms - v_terms))

    # 4) 新增未知术语：变体中出现但原文与术语表都没有的词串（启发式：重复 ≥2 次的 n-gram）
    added_terms = _added_unknown(original, variant, o_terms | set(o_times), v_terms | set(v_times))
    verdict.added_unknown_terms = added_terms

    if verdict.removed_numbers or verdict.removed_terms:
        verdict.accepted = False
        verdict.detail = (
            "Style 越权：删除了事实指纹"
            f"（数字 {verdict.removed_numbers[:5]}；术语 {verdict.removed_terms[:5]}）"
        )
    elif added_terms:
        # 新增内容：允许修辞性细节；疑似新事实 → 告警（REJECT 保守策略，防注入）
        verdict.accepted = False
        verdict.detail = f"Style 疑似注入新事实（未见于原文/术语表）：{added_terms[:5]}"
    else:
        verdict.detail = "仅 FLEXIBLE 层差异（句式/措辞/意象），未触碰事实"
    return verdict


def _added_unknown(
    original: str,
    variant: str,
    original_hits: set[str],
    variant_hits: set[str],
    *,
    min_occurrences: int = 2,
    max_terms: int = 10,
) -> list[str]:
    """启发式提取变体新增的疑似事实词（字符 n-gram 窗口计数）。

    规则：变体中重复出现 ≥2 次的 3-gram（原文无此 3-gram）→ 疑似新叙事要素；
    无 3-gram 命中时回退到 2-gram。单次出现视为修辞性细节（FLEXIBLE 层合法）。
    """
    from collections import Counter

    def grams(text: str, n: int) -> list[str]:
        chs = [c for c in text if "\u4e00" <= c <= "\u9fff"]
        return ["".join(chs[i : i + n]) for i in range(len(chs) - n + 1)]

    o3 = set(grams(original, 3))
    v3c = Counter(grams(variant, 3))
    added: list[str] = []
    for g, cnt in sorted(v3c.items(), key=lambda kv: -kv[1]):
        if g in o3 or g in original_hits or g in variant_hits:
            continue
        if cnt < min_occurrences:
            continue
        if not any(g in a or a in g for a in added):
            added.append(g)
        if len(added) >= max_terms:
            break
    if not added:
        o2 = set(grams(original, 2))
        v2c = Counter(grams(variant, 2))
        for g, cnt in sorted(v2c.items(), key=lambda kv: -kv[1]):
            if g in o2 or g in original_hits or g in variant_hits:
                continue
            if cnt < min_occurrences:
                continue
            if not any(g in a or a in g for a in added):
                added.append(g)
            if len(added) >= max_terms:
                break
    return added


