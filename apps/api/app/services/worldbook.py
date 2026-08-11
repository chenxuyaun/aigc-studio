"""世界书引擎（SillyTavern World Info 的轻量适配）。

匹配流程（对齐 ST 1.18 核心逻辑）：
1. 构建扫描缓冲：最近 N 条消息倒序拼接（\x01 分隔，防整词匹配跨消息）
2. constant 条目无条件激活；其余按主关键词匹配（支持 /正则/ 语法、整词、大小写）
3. selective 条目用次关键词二次判定（AND_ANY/AND_ALL/NOT_ANY/NOT_ALL）
4. probability 概率过滤；按 order 降序排序
5. 预算上限（估算 token），超出停止注入
6. 按 position 分发：before（主提示前）/ after（主提示后）/ atDepth（聊天中部第 depth 条后）

估算 token：中文约 1 字/token、英文约 2 字符/token 的粗略折中（len//2），仅用于预算裁剪。
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any

_SEP = "\x01"


def _load_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x) for x in v if x]
    except ValueError, TypeError:
        pass
    return []


def estimate_tokens(text: str) -> int:
    """粗略 token 估算（预算裁剪用）。"""
    if not text:
        return 0
    return max(1, len(text) // 2)


def _keyword_matches(keyword: str, buffer: str, case_sensitive: bool, whole_words: bool) -> bool:
    """单个关键词匹配：/regex/ 语法优先，否则字符串/整词匹配。"""
    km = re.fullmatch(r"/(.+)/", keyword, re.S)
    if km:
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            return re.search(km.group(1), buffer, flags) is not None
        except re.error:
            return False
    if not case_sensitive:
        keyword = keyword.lower()
        buffer = buffer.lower()
    if whole_words:
        esc = re.escape(keyword)
        # 关键词含分隔符（如 "a b"）时用包含匹配
        if " " in keyword.strip():
            return keyword in buffer
        return re.search(rf"(?:^|\W)({esc})(?:$|\W)", buffer) is not None
    return keyword in buffer


def _selective_pass(keysecondary: list[str], buffer: str, logic: str) -> bool:
    """次关键词判定。空次键列表视为通过。"""
    if not keysecondary:
        return True
    hits = [_keyword_matches(k, buffer, False, False) for k in keysecondary]
    if logic == "AND_ALL":
        return all(hits)
    if logic == "NOT_ANY":
        return not any(hits)
    if logic == "NOT_ALL":
        return not all(hits)
    return any(hits)  # AND_ANY 默认


@dataclass
class WorldBookHit:
    entry_id: str
    content: str
    position: str
    order: int
    depth: int = 4
    role: str = "system"


@dataclass
class WorldBookResult:
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    at_depth: list[WorldBookHit] = field(default_factory=list)
    activated: list[str] = field(default_factory=list)


def _entry_get(entry: Any, field: str, default: Any = None) -> Any:
    """ORM 对象或 dict 统一取值。"""
    if isinstance(entry, dict):
        return entry.get(field, default)
    return getattr(entry, field, default)


def match_worldbook(
    entries: list[Any],
    messages: list[str],
    *,
    max_depth: int = 6,
    budget_tokens: int = 600,
    rng: random.Random | None = None,
) -> WorldBookResult:
    """在世界书条目列表中做关键词扫描。

    entries: ORM 对象或 dict（需含 id/keywords/keysecondary/constant/selective/
             selective_logic/position/order_value/depth/role/case_sensitive/
             match_whole_words/probability/enabled/content 字段）
    messages: 按时间顺序的最近消息文本（越新越靠后）
    """
    rng = rng or random.Random()
    # 扫描缓冲：最近 max_depth 条，倒序拼接
    recent = messages[-max_depth:]
    buffer = _SEP.join(reversed(recent))
    result = WorldBookResult()
    used = 0

    candidates: list[WorldBookHit] = []
    for e in entries:
        if not _entry_get(e, "enabled", True):
            continue
        keywords = _load_json_list(_entry_get(e, "keywords"))
        if not keywords:
            # 兼容旧字段 keyword
            legacy = _entry_get(e, "keyword", "")
            if legacy:
                keywords = [legacy]
        constant = bool(_entry_get(e, "constant", False))
        case_sensitive = bool(_entry_get(e, "case_sensitive", False))
        whole_words = bool(_entry_get(e, "match_whole_words", False))
        selective = bool(_entry_get(e, "selective", True))
        logic = _entry_get(e, "selective_logic", "AND_ANY")
        keysecondary = _load_json_list(_entry_get(e, "keysecondary"))
        probability = int(_entry_get(e, "probability", 100))
        position = _entry_get(e, "position", "before")
        order = int(_entry_get(e, "order_value", 100))
        depth = int(_entry_get(e, "depth", 4))
        role = _entry_get(e, "role", "system")
        content = _entry_get(e, "content", "")
        entry_id = _entry_get(e, "id", "")

        if constant:
            pass  # 常驻直接激活
        elif (
            not keywords
            or not any(_keyword_matches(k, buffer, case_sensitive, whole_words) for k in keywords)
            or (selective and not _selective_pass(keysecondary, buffer, logic))
        ):
            continue
        if probability < 100 and rng.randint(1, 100) > probability:
            continue
        candidates.append(
            WorldBookHit(
                entry_id=entry_id,
                content=content,
                position=position if position in ("before", "after", "atDepth") else "before",
                order=order,
                depth=depth,
                role=role,
            )
        )

    # order 降序（ST: sortFn = b.order - a.order）
    candidates.sort(key=lambda h: h.order, reverse=True)
    for hit in candidates:
        tok = estimate_tokens(hit.content)
        if used + tok > budget_tokens:
            continue
        used += tok
        if hit.position == "after":
            result.after.append(hit.content)
        elif hit.position == "atDepth":
            result.at_depth.append(hit)
        else:
            result.before.append(hit.content)
        result.activated.append(hit.entry_id)
    return result


# ==== ST lorebook JSON 导入导出（生态互通） ====

_ST_LOGIC_MAP = {"AND_ANY": 0, "NOT_ALL": 1, "NOT_ANY": 2, "AND_ALL": 3}
_ST_LOGIC_REV = {v: k for k, v in _ST_LOGIC_MAP.items()}
_ST_POSITION_MAP = {"before": 0, "after": 1, "atDepth": 4}


def lorebook_to_st(entries: list[Any], book_name: str = "角色扮演世界书") -> dict[str, Any]:
    """roleplay_lore_entries → SillyTavern lorebook JSON。"""
    st_entries: dict[str, dict[str, Any]] = {}
    for i, e in enumerate(entries):
        keywords = _load_json_list(getattr(e, "keywords", None) or e.keywords)
        if not keywords:
            legacy = getattr(e, "keyword", "")
            keywords = [legacy] if legacy else []
        st_entries[str(i)] = {
            "uid": i,
            "key": keywords,
            "keysecondary": _load_json_list(getattr(e, "keysecondary", None) or "[]"),
            "comment": "",
            "content": getattr(e, "content", ""),
            "constant": bool(getattr(e, "constant", False)),
            "vectorized": False,
            "selective": bool(getattr(e, "selective", True)),
            "selectiveLogic": _ST_LOGIC_MAP.get(getattr(e, "selective_logic", "AND_ANY"), 0),
            "addMemo": False,
            "order": int(getattr(e, "order_value", 100)),
            "position": _ST_POSITION_MAP.get(getattr(e, "position", "before"), 0),
            "disable": not bool(getattr(e, "enabled", True)),
            "excludeRecursion": False,
            "preventRecursion": False,
            "delayUntilRecursion": False,
            "probability": int(getattr(e, "probability", 100)),
            "useProbability": True,
            "depth": int(getattr(e, "depth", 4)),
            "role": {"system": 0, "user": 1, "assistant": 2}.get(getattr(e, "role", "system"), 0),
            "caseSensitive": bool(getattr(e, "case_sensitive", False)) or None,
            "matchWholeWords": bool(getattr(e, "match_whole_words", False)) or None,
            "displayIndex": i,
        }
    return {"name": book_name, "entries": st_entries}


def lorebook_from_st(data: dict[str, Any]) -> list[dict[str, Any]]:
    """SillyTavern lorebook JSON → roleplay_lore_entries 字段列表。"""
    entries_raw = data.get("entries") or {}
    out: list[dict[str, Any]] = []
    for _uid, e in entries_raw.items():
        if not isinstance(e, dict):
            continue
        keywords = e.get("key") or []
        out.append(
            {
                "keywords": [str(k) for k in keywords if k],
                "keysecondary": [str(k) for k in (e.get("keysecondary") or []) if k],
                "content": str(e.get("content") or ""),
                "constant": bool(e.get("constant", False)),
                "selective": bool(e.get("selective", True)),
                "selective_logic": _ST_LOGIC_REV.get(int(e.get("selectiveLogic", 0)), "AND_ANY"),
                "position": {0: "before", 1: "after", 4: "atDepth"}.get(
                    int(e.get("position", 0)), "before"
                ),
                "order_value": int(e.get("order", 100)),
                "depth": int(e.get("depth", 4)),
                "role": {0: "system", 1: "user", 2: "assistant"}.get(
                    int(e.get("role", 0)), "system"
                ),
                "probability": int(e.get("probability", 100)),
                "enabled": not bool(e.get("disable", False)),
                "case_sensitive": bool(e.get("caseSensitive", False)),
                "match_whole_words": bool(e.get("matchWholeWords", False)),
            }
        )
    return out
