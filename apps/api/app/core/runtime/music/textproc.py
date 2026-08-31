"""Core Runtime - Music 文本处理（P1-1 从 api/v1/generations/music.py 抽离）。

- _extract_json: 容错解析 LLM 输出的 JSON（剥离 markdown 代码块/前后杂文本）
- _transcript: 多轮对话 → 可投递给单 prompt 的文本
- _transcript_block: 讨论记录 → 文本（从最新往前截断）
- _shuffled_transcript: 裁决去位置偏见（随机打乱发言块顺序）

纯函数，无任何 I/O。
"""
from __future__ import annotations

import json
import random
import re
from typing import Any


def _extract_json(text: str) -> dict[str, Any]:
    """容错解析 LLM 输出的 JSON（剥离 markdown 代码块/前后杂文本）。"""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"error": "AI 输出解析失败", "raw": text[:500]}


def _transcript(messages: list[dict[str, str]], style: str) -> str:
    """多轮对话 → 可投递给单 prompt 的文本（保留最近 20 条）。"""
    lines: list[str] = []
    if style:
        lines.append(f"（本次创作固定风格：{style}，讨论与修改都要贴合该风格）")
    for m in messages[-20:]:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"用户：{content}")
        elif role == "assistant":
            lines.append(f"助手：{content}")
        else:
            lines.append(content)
    return "\n\n".join(lines)


def _transcript_block(rounds: list[dict[str, str]], limit: int = 2500) -> str:
    """讨论记录 → 文本（从最新往前截断，防定稿 prompt 超长）。"""
    parts: list[str] = []
    total = 0
    for r in reversed(rounds):
        s = f"{r['speaker']}：{r['content']}"
        if parts and total + len(s) > limit:
            break
        parts.append(s)
        total += len(s)
    return "\n".join(reversed(parts)) or "（无讨论记录）"


def _shuffled_transcript(rounds: list[dict[str, str]], limit: int = 2500) -> str:
    """裁决去位置偏见：随机打乱发言块顺序（保留发言者名），打破 primacy/recency 锚定。

    搜索结论（Judging the Judges）：judge 有系统性位置偏见，机械修复（随机化/轮换）
    比「写更公正的 rubric」有效。主理人裁决时应按观点质量而非发言顺序——随机化
    迫使它逐条看观点内容（每个块都带 speaker 名，可归因），而非"谁最后说就听谁的"。
    """
    shuffled = list(rounds)
    random.shuffle(shuffled)
    return _transcript_block(shuffled, limit)
