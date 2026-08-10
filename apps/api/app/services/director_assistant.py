"""群聊 AI 导演：群里发「@AI 导演」→ 按戏剧节奏指挥群内演出（真人+AI 角色同场）。

- 开演/推进：@AI 导演（或 @AI 导演：下一场/第X幕）→ 基于群主题/角色/已演历史，
  输出本场演出指令（场景/出场/目标/节拍/台词提示）
- 总结沉淀：@AI 导演：总结 → 把已演内容总结为剧本段落（可复制存档）
回复以 🎬【AI 导演】 开头标记，落库后群成员都能看到、都能继续 @ 指挥。
"""

# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roleplay_character import RoleplayCharacter
from app.models.roleplay_chat import RoleplayChat
from app.services import sessions
from app.services.provider_resolver import resolve_text_provider

DIRECTOR_CMD_PREFIXES = ("@AI 导演", "@AI导演", "@ai 导演", "@ai导演")
DIRECTOR_TAG = "🎬【AI 导演】"
_SUMMARY_HINTS = ("总结", "复盘", "存档", "成文")


def is_director_cmd(content: str) -> bool:
    """消息是否命中「@AI 导演」指令。"""
    c = (content or "").strip()
    return any(c.startswith(p) for p in DIRECTOR_CMD_PREFIXES)


def is_summary_cmd(content: str) -> bool:
    """指令是否为总结/复盘类（否则视为推进演出）。"""
    c = (content or "").strip()
    return any(h in c for h in _SUMMARY_HINTS)


def _strip_prefix(content: str) -> str:
    c = (content or "").strip()
    for p in DIRECTOR_CMD_PREFIXES:
        if c.startswith(p):
            return c[len(p) :].lstrip("：:，, ")
    return c


_DIRECTOR_SYSTEM = """你是「AI 导演」：掌控全局的戏剧导演，负责指挥一群演员（真人 + AI 角色同场）一场一场完成作品。
你有完整的戏剧素养：场面调度、冲突节奏、潜台词、台词准确性。
- 输出**可执行的演出指令**，格式：
  场景设定（地点/时间/氛围）
  出场角色（从角色表中挑，注明谁主导）
  本场目标（这场戏要达成什么）
  剧情节拍（发生什么→冲突/转折→留下什么钩子）
  台词提示（给 1-2 个角色的具体台词方向，贴合其性格）
- 简洁有力，200-300 字；始终基于已演内容推进，不重复已演情节；接近结尾时安排收尾场。
- 语言跟随用户（默认中文）。"""

_SUMMARY_SYSTEM = """你是「AI 导演」兼场记。把群里已演出的内容总结成标准剧本段落：
- 格式：场景标题（地点/时间）+ 场景描述 + 角色对白（【角色名】：台词）+ 转场提示
- 忠实于已演内容，可适度润色台词与补全动作提示，不编造未演情节
- 300-500 字，可直接复制存档为剧本章节"""


from app.services.text_utils import result_text as _result_text


async def _load_cast(db: AsyncSession, chat: RoleplayChat) -> list[dict[str, str]]:
    """群角色表：asset_id → 名字/性格/定位（用于导演安排出场）。"""
    import json as _json

    try:
        char_ids = _json.loads(chat.character_asset_ids) if chat.character_asset_ids else []
    except Exception:
        char_ids = []
    if not char_ids:
        return []
    rows = (
        await db.execute(
            select(RoleplayCharacter).where(
                RoleplayCharacter.asset_id.in_(char_ids)
            )
        )
    ).scalars().all()
    return [
        {
            "name": str(r.name or r.asset_id),
            "personality": str(r.personality or "")[:100],
            "role": str(r.description or "")[:60],
        }
        for r in rows
    ]


def _format_cast(cast: list[dict[str, str]]) -> str:
    if not cast:
        return "（群内暂无角色卡，可由导演临时安排群成员身份）"
    return "\n".join(
        f"- {c['name']}：{c['personality']}" for c in cast
    )


def _history_block(history: list[dict[str, str]], limit: int = 14) -> str:
    lines = []
    for m in history[-limit:]:
        role = m.get("role", "")
        content = str(m.get("content") or "")
        if role == "user":
            lines.append(f"观众/演员：{content}")
        else:
            lines.append(f"演出：{content}")
    return "\n".join(lines) if lines else "（还没有演出记录，本场为第一场）"


async def director_chat_reply(
    db: AsyncSession,
    user_id: str,
    chat: RoleplayChat,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """群聊「@AI 导演」指令处理：开演/推进/总结 → 落库 → 返回 roleplay 同构结果。"""
    last_user = next(
        (m for m in reversed(messages) if m.get("role") == "user"), None
    )
    content = str(last_user.get("content") or "") if last_user else ""
    instruction = _strip_prefix(content)
    is_summary = is_summary_cmd(content)

    cast = await _load_cast(db, chat)
    stored = sessions.chat_messages(chat)
    history = [
        {"role": m.get("role", ""), "content": str(m.get("content") or "")}
        for m in stored
    ]
    # 已演内容只统计非指令消息（去掉本群导演/音乐助手的指令与回复之外的都算演出）
    cast_block = _format_cast(cast)
    hist_block = _history_block(history)

    try:
        resolved = await resolve_text_provider(db, "")
        provider = resolved.provider  # type: ignore[attr-defined]
        if is_summary:
            prompt = (
                f"剧组：《{chat.title}》\n\n已演内容：\n{hist_block}\n\n"
                "请总结为剧本段落。"
            )
            result = await provider.generate(
                prompt, resolved.model, system=_SUMMARY_SYSTEM, temperature=0.7
            )
            reply = f"**剧本段落（可复制存档）**\n\n{_result_text(result).strip()}"
        else:
            prompt = (
                f"剧组：《{chat.title}》\n"
                f"导演要求：{instruction or '开演（第一场）'}\n\n"
                f"角色表：\n{cast_block}\n\n已演内容：\n{hist_block}\n\n"
                "请输出本场演出指令。"
            )
            result = await provider.generate(
                prompt, resolved.model, system=_DIRECTOR_SYSTEM, temperature=0.85
            )
            reply = _result_text(result).strip()
    except Exception as exc:
        return {"error": f"导演调度失败：{str(exc)[:200]}"}

    # 落库：用户指令（若服务端尚未记录）+ 导演指令
    if last_user and (
        not stored or stored[-1].get("content") != last_user.get("content")
    ):
        await sessions.append_message(
            db, chat, {"role": "user", "content": content}
        )
    await sessions.append_message(
        db, chat, {"role": "assistant", "content": DIRECTOR_TAG + reply}
    )

    return {
        "reply": DIRECTOR_TAG + reply,
        "mood": "",
        "mood_delta": 0,
        "character": {"names": ["AI 导演"]},
        "model": "director-assistant",
        "chat_id": chat.id,
        "director": True,
    }
