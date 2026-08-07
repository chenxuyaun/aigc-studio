"""角色扮演会话服务：服务端持久化对话历史 + SillyTavern JSONL 导出/导入。

ST JSONL 格式：首行 = metadata JSON（chat_metadata 含 integrity/user_name/character_name），
后续每行一条消息 {name, is_user, is_system, send_date, mes}。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roleplay_chat import RoleplayChat


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_messages(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def dump_messages(messages: list[dict[str, Any]]) -> str:
    return json.dumps(messages, ensure_ascii=False)


async def get_chat(db: AsyncSession, user_id: str, chat_id: str) -> RoleplayChat | None:
    return (
        await db.execute(
            select(RoleplayChat).where(
                RoleplayChat.id == chat_id, RoleplayChat.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def list_chats(db: AsyncSession, user_id: str) -> list[RoleplayChat]:
    rows = await db.execute(
        select(RoleplayChat)
        .where(RoleplayChat.user_id == user_id)
        .order_by(RoleplayChat.updated_at.desc())
    )
    return list(rows.scalars().all())


def chat_messages(chat: RoleplayChat) -> list[dict[str, Any]]:
    return _load_messages(chat.messages)


async def create_chat(
    db: AsyncSession,
    user_id: str,
    *,
    title: str = "",
    character_asset_ids: list[str],
    group: bool = False,
    model: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    settings: dict[str, Any] | None = None,
) -> RoleplayChat:
    chat = RoleplayChat(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title or f"会话 {datetime.now(UTC).strftime('%m-%d %H:%M')}",
        character_asset_ids=json.dumps(character_asset_ids, ensure_ascii=False),
        group=group,
        messages="[]",
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        settings=json.dumps(settings or {}, ensure_ascii=False),
    )
    db.add(chat)
    await db.flush()
    return chat


async def append_message(db: AsyncSession, chat: RoleplayChat, msg: dict[str, Any]) -> None:
    """追加消息并更新 updated_at。"""
    messages = chat_messages(chat)
    entry = dict(msg)
    entry.setdefault("created_at", _now_iso())
    messages.append(entry)
    chat.messages = dump_messages(messages)
    chat.updated_at = datetime.now(UTC)


async def replace_messages(
    db: AsyncSession, chat: RoleplayChat, messages: list[dict[str, Any]]
) -> None:
    chat.messages = dump_messages(messages)
    chat.updated_at = datetime.now(UTC)


async def delete_chat(db: AsyncSession, chat: RoleplayChat) -> None:
    await db.delete(chat)


def export_jsonl(chat: RoleplayChat) -> str:
    """导出为 SillyTavern JSONL（首行 metadata + 每行消息）。"""
    try:
        char_ids = json.loads(chat.character_asset_ids or "[]")
    except (ValueError, TypeError):
        char_ids = []
    meta = {
        "chat_metadata": {
            "integrity": str(uuid.uuid4()),
            "user_name": "用户",
            "character_name": ",".join(char_ids) or "角色扮演",
        },
        "is_group": chat.group,
        "model": chat.model,
    }
    lines = [json.dumps(meta, ensure_ascii=False)]
    for m in chat_messages(chat):
        role = m.get("role")
        lines.append(
            json.dumps(
                {
                    "name": "用户" if role == "user" else m.get("speaker") or "角色",
                    "is_user": role == "user",
                    "is_system": False,
                    "send_date": m.get("created_at", _now_iso()),
                    "mes": m.get("content", ""),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines)


def import_jsonl(db: AsyncSession, user_id: str, content: str) -> RoleplayChat | None:
    """导入 SillyTavern JSONL → 新建会话。返回 chat（未 flush 到 DB，调用方 commit）。"""
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if not lines:
        return None
    messages: list[dict[str, Any]] = []
    character_ids: list[str] = []
    for ln in lines[1:]:
        try:
            obj = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(obj, dict) or "mes" not in obj:
            continue
        messages.append(
            {
                "role": "assistant" if obj.get("is_user") is False else "user",
                "content": str(obj.get("mes", "")),
                "created_at": obj.get("send_date") or _now_iso(),
            }
        )
    title = "导入会话"
    try:
        meta = json.loads(lines[0])
        if isinstance(meta, dict):
            cm = meta.get("chat_metadata") or {}
            cname = cm.get("character_name")
            if isinstance(cname, str) and cname and cname != "角色扮演":
                character_ids = [cname]
            if meta.get("is_group"):
                pass
            title = f"导入 {str(cname or '会话')[:40]}"
    except ValueError:
        pass
    chat = RoleplayChat(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title,
        character_asset_ids=json.dumps(character_ids, ensure_ascii=False),
        group=False,
        messages=dump_messages(messages),
        settings="{}",
    )
    db.add(chat)
    return chat


def remove_message(chat: RoleplayChat, index: int) -> bool:
    """按索引删除会话消息（越界返回 False）。"""
    messages = chat_messages(chat)
    if index < 0 or index >= len(messages):
        return False
    messages.pop(index)
    chat.messages = dump_messages(messages)
    return True


def get_settings(chat: RoleplayChat) -> dict[str, Any]:
    """解析会话 settings JSON。"""
    try:
        v = json.loads(chat.settings or "{}")
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


def set_settings(chat: RoleplayChat, settings: dict[str, Any]) -> None:
    """覆写会话 settings。"""
    chat.settings = json.dumps(settings, ensure_ascii=False)


async def branch_chat(
    db: AsyncSession, user_id: str, source: RoleplayChat, index: int
) -> RoleplayChat | None:
    """从源会话第 index 条消息（含）之后分叉出新会话。越界返回 None。"""
    messages = chat_messages(source)
    if index < 0 or index >= len(messages):
        return None
    new_chat = RoleplayChat(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=f"{source.title} · 分支{index + 1}",
        character_asset_ids=source.character_asset_ids,
        group=source.group,
        messages=dump_messages(messages[: index + 1]),
        model=source.model,
        temperature=source.temperature,
        max_tokens=source.max_tokens,
        top_p=source.top_p,
        settings=source.settings,
    )
    db.add(new_chat)
    await db.flush()
    return new_chat
