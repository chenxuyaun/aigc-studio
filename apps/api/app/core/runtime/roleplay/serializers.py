"""Core Runtime - Roleplay 序列化器（P1-2 从 api/v1/roleplay.py 抽离，逐字搬运）。

Model → dict 纯函数（JSON 字段解析容错）。_chat_dict 只读 chat.messages 属性，无 I/O。
"""
from __future__ import annotations

import json
from typing import Any

from app.models.roleplay_character import RoleplayCharacter
from app.models.roleplay_chat import RoleplayChat
from app.models.roleplay_lore import RoleplayLoreEntry


def _lore_dict(e: RoleplayLoreEntry) -> dict[str, Any]:
    def _j(raw: str | None) -> list[str]:
        try:
            v = json.loads(raw or "[]")
            return [str(x) for x in v] if isinstance(v, list) else []
        except (ValueError, TypeError):
            return []

    return {
        "id": e.id,
        "character_name": e.character_name,
        "project_id": e.project_id,
        "keyword": e.keyword,
        "keywords": _j(e.keywords) or ([e.keyword] if e.keyword else []),
        "keysecondary": _j(e.keysecondary),
        "content": e.content,
        "constant": bool(e.constant),
        "selective": bool(e.selective),
        "selective_logic": e.selective_logic,
        "position": e.position,
        "order_value": e.order_value,
        "depth": e.depth,
        "role": e.role,
        "scan_depth": e.scan_depth,
        "case_sensitive": bool(e.case_sensitive),
        "match_whole_words": bool(e.match_whole_words),
        "probability": e.probability,
        "enabled": bool(e.enabled),
    }


def _character_dict(c: RoleplayCharacter) -> dict[str, Any]:
    def _j(raw: str | None, default: Any) -> Any:
        try:
            return json.loads(raw or "")
        except (ValueError, TypeError):
            return default

    return {
        "asset_id": c.asset_id,
        "name": c.name,
        "description": c.description,
        "personality": c.personality,
        "scenario": c.scenario,
        "first_mes": c.first_mes,
        "mes_example": c.mes_example,
        "alternate_greetings": _j(c.alternate_greetings, []),
        "system_prompt": c.system_prompt,
        "post_history_instructions": c.post_history_instructions,
        "creator_notes": c.creator_notes,
        "tags": _j(c.tags, []),
        "character_book": _j(c.character_book, {}),
        "talkativeness": c.talkativeness,
        "depth_prompt": _j(c.depth_prompt, {}),
        "settings": _j(c.settings, {}),
    }


def _chat_dict(c: RoleplayChat) -> dict[str, Any]:
    try:
        char_ids = json.loads(c.character_asset_ids or "[]")
    except (ValueError, TypeError):
        char_ids = []
    try:
        settings = json.loads(c.settings or "{}")
    except (ValueError, TypeError):
        settings = {}
    return {
        "id": c.id,
        "title": c.title,
        "is_room": bool(c.is_room),
        "character_asset_ids": char_ids,
        "group": bool(c.group),
        "model": c.model,
        "temperature": c.temperature,
        "max_tokens": c.max_tokens,
        "top_p": c.top_p,
        "settings": settings,
        "message_count": len(_chat_messages(c)),
        "created_at": str(c.created_at) if c.created_at else "",
        "updated_at": str(c.updated_at) if c.updated_at else "",
    }


def _chat_messages(c: RoleplayChat) -> list[Any]:
    """会话消息列表（原实现在 services.sessions.chat_messages，此处内联避免反向依赖）。"""
    try:
        v = json.loads(c.messages or "[]")
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []
