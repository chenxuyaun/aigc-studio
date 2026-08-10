"""群聊音乐助手：群里发「@AI 写歌：主题」→ 直接在群里出歌词，可多轮打磨。

首轮：@AI 写歌：主题 [风格] [情绪] → 完整歌词（复用 AI 写歌 compose 提示词）
讨论轮：群历史最近一条助手回复是歌词时 → 带上下文精准修改（复用音乐讨论室人格）
回复以 🎵【AI 音乐助手】 开头标记，落库后群成员都能看到、都能继续 @ 打磨。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# 复用写歌/讨论的提示词与解析（一次性反向依赖：API 模块只承担端点组装）
from app.api.v1.generations.music import (
    _COMPOSE_PROMPT,
    _DISCUSS_SYSTEM,
    _STYLE_PROFILES,
    _extract_json,
    _transcript,
)
from app.models.roleplay_chat import RoleplayChat
from app.services import sessions
from app.services.provider_resolver import resolve_text_provider

MUSIC_CMD_PREFIXES = ("@AI 写歌", "@AI写歌", "@ai 写歌", "@ai写歌")
MUSIC_TAG = "🎵【AI 音乐助手】"
_STYLE_NAMES = ("古风", "中国风", "民谣", "流行", "R&B", "电子", "摇滚", "爵士", "嘻哈", "治愈系")
_MOOD_NAMES = ("治愈", "开心", "伤感", "热血", "浪漫", "思念", "励志", "安静")


def is_music_cmd(content: str) -> bool:
    """消息是否命中「@AI 写歌」指令。"""
    c = (content or "").strip()
    return any(c.startswith(p) for p in MUSIC_CMD_PREFIXES)


def _parse_cmd(content: str) -> tuple[str, str, str]:
    """提取指令正文与可选风格/情绪。返回 (要求文本, 风格, 情绪)。

    风格/情绪仅提取"独立成词"的出现（如「80/90 童年 民谣 伤感」），
    避免把主题中的字眼误判（如「异地的思念」的"思念"）。
    """
    c = (content or "").strip()
    for p in MUSIC_CMD_PREFIXES:
        if c.startswith(p):
            c = c[len(p) :].lstrip("：:，, ")
            break
    words = c.split()
    style = ""
    mood = ""
    for s in _STYLE_NAMES:
        if s in words:
            style = s
            words.remove(s)
            break
    for m in _MOOD_NAMES:
        if m in words:
            mood = m
            words.remove(m)
            break
    return " ".join(words).strip(" ，,。·-"), style, mood


from app.services.text_utils import result_text as _result_text


async def _compose(db: AsyncSession, theme: str, style: str, mood: str) -> str:
    """首轮：完整歌词（歌名 + 分段落歌词 + 风格说明）。"""
    style_profile = _STYLE_PROFILES.get(style, _STYLE_PROFILES["流行"])
    prompt = _COMPOSE_PROMPT.format(
        theme=theme or "（未指定主题，请自由发挥）",
        style=style or "流行",
        mood=mood or "治愈",
        language="中文",
        verse_count=2,
        style_profile=style_profile,
    )
    resolved = await resolve_text_provider(db, "")
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        prompt, resolved.model, temperature=0.95
    )
    data = _extract_json(_result_text(result))
    if data.get("error"):
        return f"歌词生成失败：{data['error']}"
    title = str(data.get("title") or "未命名")
    lyrics = str(data.get("lyrics") or "")
    style_zh = str(data.get("style_zh") or "")
    parts = [f"《{title}》", "", lyrics]
    if style_zh:
        parts += ["", f"【风格】{style_zh}"]
    return "\n".join(parts)


async def _discuss(db: AsyncSession, history: list[dict[str, str]], style: str) -> str:
    """讨论轮：带群历史上下文精准修改。"""
    prompt = _transcript(history, style)
    resolved = await resolve_text_provider(db, "")
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        prompt, resolved.model, system=_DISCUSS_SYSTEM, temperature=0.95
    )
    return _result_text(result).strip() or "（AI 没有给出修改，请换个说法再试）"


async def music_chat_reply(
    db: AsyncSession,
    user_id: str,
    chat: RoleplayChat,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """群聊「@AI 写歌」指令处理：生成/打磨 → 落库 → 返回 roleplay 同构结果。

    messages 为本次请求的全部消息（最后一条为用户指令）。
    """
    last_user = next(
        (m for m in reversed(messages) if m.get("role") == "user"), None
    )
    content = str(last_user.get("content") or "") if last_user else ""
    text, style, mood = _parse_cmd(content)

    stored = sessions.chat_messages(chat)
    last_assistant = (
        stored[-1] if stored and stored[-1].get("role") == "assistant" else None
    )
    # 群历史最近一条助手消息是音乐助手歌词 → 讨论轮（带上下文打磨）
    is_followup = bool(
        last_assistant
        and str(last_assistant.get("content") or "").startswith(MUSIC_TAG)
    )
    try:
        if is_followup:
            history: list[dict[str, str]] = [
                {"role": m.get("role", ""), "content": str(m.get("content") or "")}
                for m in stored[-11:]
            ]
            history.append({"role": "user", "content": content})
            reply = await _discuss(db, history, style)
        else:
            reply = await _compose(db, text, style, mood)
    except Exception as exc:
        return {"error": f"写歌失败：{str(exc)[:200]}"}

    # 落库：用户指令（若服务端尚未记录）+ 助手歌词
    if last_user and (
        not stored or stored[-1].get("content") != last_user.get("content")
    ):
        await sessions.append_message(
            db, chat, {"role": "user", "content": content}
        )
    await sessions.append_message(
        db, chat, {"role": "assistant", "content": MUSIC_TAG + reply}
    )

    return {
        "reply": MUSIC_TAG + reply,
        "mood": "",
        "mood_delta": 0,
        "character": {"names": ["AI 音乐助手"]},
        "model": "music-assistant",
        "chat_id": chat.id,
        "music": True,
    }
