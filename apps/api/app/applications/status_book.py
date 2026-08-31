"""状态批注账本：正文/对话里登记角色状态变化（借鉴 Openwrite 的人物时态批注）。

格式：`//**角色名[类别]：旧值 -> 新值**`（支持 -> / → / ⇒；旧值可省略）
例：`//**老周[伤势]：左臂轻伤 -> 已恢复**` `//**翠翠[心情]：平静**`

- 批注不计入正文/消息（落库前剥离）
- 系统自动登记到会话状态账本，跨对话保持角色状态一致
- 旧值不匹配时给出连续性冲突警告（防状态错乱）
"""

from __future__ import annotations

import re
from typing import Any

# //**名字[类别]：旧 -> 新**  （→ 或 ⇒ 等价；旧值可省略为「：新**」）
_ANNOTATION_RE = re.compile(
    r"//\*\*\s*([^\[\]]+?)\s*\[\s*([^\[\]]+?)\s*\]\s*[：:]\s*"
    r"(?:([^*\[\]→➔>]+?)\s*(?:->|→|⇒)\s*)?([^*]+?)\s*\*\*"
)


def parse_annotations(text: str) -> list[dict[str, str]]:
    """解析文本中的状态批注，返回 [{character, category, old, new}]。"""
    out: list[dict[str, str]] = []
    for m in _ANNOTATION_RE.finditer(text or ""):
        out.append(
            {
                "character": m.group(1).strip(),
                "category": m.group(2).strip(),
                "old": (m.group(3) or "").strip(),
                "new": (m.group(4) or "").strip(),
            }
        )
    return out


def strip_annotations(text: str) -> str:
    """从文本中移除批注（批注不计入正文/成书）。"""
    return _ANNOTATION_RE.sub("", text or "").strip()


def apply_book(
    book: dict[str, dict[str, str]], annotations: list[dict[str, str]]
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """把批注合并进账本 {角色: {类别: 当前值}}，返回 (新账本, 冲突警告)。"""
    warnings: list[str] = []
    for a in annotations:
        ch = a["character"]
        cat = a["category"]
        new = a["new"]
        old = a["old"]
        if not ch or not cat or not new:
            continue
        current = (book.get(ch) or {}).get(cat, "")
        if old and current and current != old:
            warnings.append(
                f"⚠ {ch}的「{cat}」状态冲突：批注写旧值「{old}」，账本当前是「{current}」"
            )
        book.setdefault(ch, {})[cat] = new
    return book, warnings


def book_to_text(book: dict[str, dict[str, str]]) -> str:
    """账本 → 注入文本（无条目返回空串）。"""
    if not book:
        return ""
    lines = []
    for ch, cats in book.items():
        if cats:
            lines.append(f"- {ch}：" + "；".join(f"{k}={v}" for k, v in cats.items()))
    return "\n".join(lines) if lines else ""


def merge_settings(settings: dict[str, Any], book: dict[str, dict[str, str]]) -> dict[str, Any]:
    """把账本合并进会话 settings（保留其他字段）。"""
    merged = dict(settings or {})
    merged["status_book"] = book
    return merged
