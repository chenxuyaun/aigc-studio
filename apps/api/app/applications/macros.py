"""宏系统（SillyTavern macros 的轻量适配）。

在角色卡字段、世界书 content、系统提示模板中支持 {{...}} 占位符：

名字类：{{char}} {{user}} {{group}} {{groupNotMuted}}
字段类：{{charDescription}} {{charPersonality}} {{charScenario}} {{charPrompt}} {{charInstruction}}
时间类：{{time}} {{date}} {{weekday}} {{isotime}} {{datetimeformat::fmt}}
随机类：{{random::a::b}}（每次重掷） {{pick::a::b}}（确定性） {{roll::1d20}}
工具类：{{newline}} {{newline::n}} {{trim}} {{noop}} {{input}} {{lastMessage}} {{lastUserMessage}}
遗留形：<USER> <BOT> <CHAR> <GROUP>

context 字段：char（角色卡 dict）、user（用户名）、group（群聊名单）、input（当前输入）、
last_message、last_user_message、seed（pick 确定性种子基）
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import UTC, datetime
from typing import Any

_TWO_BRACE_RE = re.compile(r"\{\{([^{}]+)\}\}")
_PICK_RE = re.compile(r"pick(?:::([^{}]*))?")
_ROLL_RE = re.compile(r"roll::([0-9dDhL+-]+)")
_RANDOM_RE = re.compile(r"random(?:::(.*))?")


def _now() -> datetime:
    return datetime.now(UTC)


def _fmt(dt: datetime, fmt: str = "%H:%M") -> str:
    return dt.strftime(fmt)


def _deterministic_pick(seed_base: str, options: list[str], offset: int) -> str:
    h = hashlib.sha256(f"{seed_base}#{offset}".encode()).hexdigest()
    return options[int(h, 16) % len(options)]


def _roll(spec: str) -> str:
    """droll 子集：NdM、NdM+H、NdM-H、纯数字。"""
    spec = spec.strip()
    m = re.fullmatch(r"(\d+)[dD](\d+)([+-]\d+)?", spec)
    if m:
        count, sides = int(m.group(1)), int(m.group(2))
        bonus = int(m.group(3) or 0)
        total = sum(random.randint(1, sides) for _ in range(count)) + bonus
        return str(total)
    if spec.isdigit():
        return spec
    return spec


def _expand_macro(name: str, ctx: dict[str, Any], offset: int) -> str:
    """展开单个 {{...}} 宏体；无法识别返回原样。"""
    char: dict[str, str] = ctx.get("char") or {}
    user = ctx.get("user") or "用户"
    group = ctx.get("group") or ""
    trimmed = name.strip()
    if not trimmed:
        return ""
    low = trimmed.lower()
    # 名字类
    if low == "char":
        return char.get("name") or "角色"
    if low == "user":
        return user
    if low == "group":
        return group
    if low == "groupnotmuted":
        return group
    if low == "notchar":
        return ""
    # 字段类
    field_map = {
        "chardescription": "description",
        "charpersonality": "personality",
        "charscenario": "scenario",
        "charprompt": "system_prompt",
        "charinstruction": "post_history_instructions",
        "charfirstmessage": "first_mes",
        "charcreatorsnotes": "creator_notes",
        "charversion": "character_version",
    }
    if low in field_map:
        return char.get(field_map[low]) or ""
    if low == "persona":
        return ctx.get("persona_description") or ""
    # 时间类
    if low == "time":
        return _fmt(_now())
    if low == "date":
        return _fmt(_now(), "%Y-%m-%d")
    if low == "weekday":
        return _fmt(_now(), "%A")
    if low == "isotime":
        return _now().isoformat()
    dtm = re.fullmatch(r"datetimeformat::(.+)", trimmed, re.S)
    if dtm:
        return _fmt(_now(), dtm.group(1).strip())
    # 随机/骰子
    if low.startswith("random"):
        m = _RANDOM_RE.fullmatch(trimmed)
        if m:
            opts = [p for p in (m.group(1) or "").split("::") if p != ""]
            if not opts:
                return ""
            return random.choice(opts)
    if low.startswith("pick"):
        m = _PICK_RE.fullmatch(trimmed)
        if m:
            opts = [p for p in (m.group(1) or "").split("::") if p != ""]
            if not opts:
                return ""
            return _deterministic_pick(str(ctx.get("seed") or ""), opts, offset)
    if low.startswith("roll"):
        m = _ROLL_RE.fullmatch(trimmed)
        if m:
            return _roll(m.group(1))
    # 工具类
    if low == "newline":
        return "\n"
    nw = re.fullmatch(r"newline::(\d+)", trimmed)
    if nw:
        return "\n" * int(nw.group(1))
    if low == "trim":
        return ""
    if low == "noop":
        return ""
    if low == "input":
        return ctx.get("input") or ""
    if low == "lastmessage":
        return ctx.get("last_message") or ""
    if low == "lastusermessage":
        return ctx.get("last_user_message") or ""
    return f"{{{{{name}}}}}"


def substitute(text: str, ctx: dict[str, Any] | None = None) -> str:
    """展开文本中的全部宏；未识别的宏保持原样（避免误伤内容）。"""
    if not text:
        return text
    ctx = ctx or {}

    def _repl(m: re.Match[str]) -> str:
        return _expand_macro(m.group(1), ctx, m.start())

    out = _TWO_BRACE_RE.sub(_repl, text)
    # 遗留单括号形式
    legacy = {
        "<USER>": ctx.get("user") or "用户",
        "<CHAR>": (ctx.get("char") or {}).get("name") or "角色",
        "<BOT>": (ctx.get("char") or {}).get("name") or "角色",
        "<GROUP>": ctx.get("group") or "",
    }
    for k, v in legacy.items():
        if k in out:
            out = out.replace(k, v)
    return out
