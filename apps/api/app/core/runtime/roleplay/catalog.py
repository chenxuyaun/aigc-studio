"""Core Runtime - Roleplay 目录 CRUD（P1-2 从 api/v1/roleplay.py 抽离，逐字搬运）。

世界书（lore）/ 正则脚本 / 快捷回复 / 用户形象 —— 直连 DB 的薄查询层。
add/update 类函数的 req 参数为 API 层请求 schema 实例（鸭子类型，本模块不反向 import schema）。
导出 lore 返回 ST lorebook dict（Response 组装留在路由）。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.core.runtime.roleplay.serializers import _lore_dict
from app.models.quick_reply import QuickReply
from app.models.regex_script import RegexScript
from app.models.roleplay_lore import RoleplayLoreEntry
from app.models.roleplay_persona import RoleplayPersona
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ==== 世界书 ====


def _lore_keywords(req: Any) -> list[str]:
    return req.keywords or ([req.keyword] if req.keyword else [])


async def lore_list(
    db: AsyncSession,
    user_id: str,
    character_name: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    """世界书条目列表（全字段；project_id 过滤创作项目作用域）。"""
    stmt = select(RoleplayLoreEntry).where(RoleplayLoreEntry.user_id == user_id)
    if character_name:
        stmt = stmt.where(RoleplayLoreEntry.character_name == character_name)
    if project_id:
        stmt = stmt.where(RoleplayLoreEntry.project_id == project_id)
    else:
        # 默认只显示常规条目（创作项目条目在项目页用 project_id 过滤查看）
        stmt = stmt.where(RoleplayLoreEntry.project_id.is_(None))
    stmt = stmt.order_by(RoleplayLoreEntry.order_value.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_lore_dict(e) for e in rows]}


async def lore_add(db: AsyncSession, user_id: str, req: Any) -> dict[str, Any]:
    """新增世界书条目（全字段）。"""
    keywords = _lore_keywords(req)
    entry = RoleplayLoreEntry(
        id=str(uuid.uuid4()),
        user_id=user_id,
        character_name=req.character_name,
        project_id=req.project_id,
        keyword=keywords[0] if keywords else "",
        keywords=json.dumps(keywords, ensure_ascii=False),
        keysecondary=json.dumps(req.keysecondary, ensure_ascii=False),
        content=req.content,
        constant=req.constant,
        selective=req.selective,
        selective_logic=req.selective_logic,
        position=req.position,
        order_value=req.order_value,
        depth=req.depth,
        role=req.role,
        scan_depth=req.scan_depth,
        case_sensitive=req.case_sensitive,
        match_whole_words=req.match_whole_words,
        probability=req.probability,
        enabled=req.enabled,
    )
    db.add(entry)
    await db.commit()
    return {"ok": True, "id": entry.id}


async def lore_update(
    db: AsyncSession,
    user_id: str,
    entry_id: str,
    req: Any,
) -> dict[str, Any]:
    """编辑世界书条目。"""
    entry = (
        await db.execute(
            select(RoleplayLoreEntry).where(
                RoleplayLoreEntry.id == entry_id,
                RoleplayLoreEntry.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="条目不存在或无权访问")
    keywords = _lore_keywords(req)
    entry.character_name = req.character_name
    entry.project_id = req.project_id
    entry.keyword = keywords[0] if keywords else ""
    entry.keywords = json.dumps(keywords, ensure_ascii=False)
    entry.keysecondary = json.dumps(req.keysecondary, ensure_ascii=False)
    entry.content = req.content
    entry.constant = req.constant
    entry.selective = req.selective
    entry.selective_logic = req.selective_logic
    entry.position = req.position
    entry.order_value = req.order_value
    entry.depth = req.depth
    entry.role = req.role
    entry.scan_depth = req.scan_depth
    entry.case_sensitive = req.case_sensitive
    entry.match_whole_words = req.match_whole_words
    entry.probability = req.probability
    entry.enabled = req.enabled
    await db.commit()
    return {"ok": True}


async def lore_delete(db: AsyncSession, user_id: str, entry_id: str) -> dict[str, Any]:
    """删除世界书条目。"""
    entry = (
        await db.execute(
            select(RoleplayLoreEntry).where(
                RoleplayLoreEntry.id == entry_id,
                RoleplayLoreEntry.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="条目不存在或无权访问")
    await db.delete(entry)
    await db.commit()
    return {"ok": True}


async def lore_export_book(
    db: AsyncSession,
    user_id: str,
    character_name: str = "",
) -> dict[str, Any]:
    """导出世界书为 SillyTavern lorebook dict（可按角色过滤）。"""
    from app.services.worldbook import lorebook_to_st

    stmt = select(RoleplayLoreEntry).where(RoleplayLoreEntry.user_id == user_id)
    if character_name:
        stmt = stmt.where(RoleplayLoreEntry.character_name == character_name)
    rows = (await db.execute(stmt)).scalars().all()
    return lorebook_to_st(list(rows), "AIGC 角色扮演世界书")


async def lore_import_st(db: AsyncSession, user_id: str, data: str) -> dict[str, Any]:
    """导入 SillyTavern lorebook JSON → 世界书条目（character_name 为空 = 全局书）。"""
    from app.services.worldbook import lorebook_from_st

    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大（>5MB）")
    try:
        book = json.loads(data)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="无法解析 JSON（需为 SillyTavern lorebook 格式）"
        ) from None
    if not isinstance(book, dict) or not isinstance(book.get("entries"), dict):
        raise HTTPException(status_code=400, detail="缺少 entries 字段（非 lorebook 格式）")
    entries = lorebook_from_st(book)
    for e in entries:
        keywords = e.pop("keywords")
        row = RoleplayLoreEntry(
            id=str(uuid.uuid4()),
            user_id=user_id,
            character_name=None,
            keyword=keywords[0] if keywords else "",
            keywords=json.dumps(keywords, ensure_ascii=False),
            keysecondary=json.dumps(e.pop("keysecondary"), ensure_ascii=False),
            **e,
        )
        db.add(row)
    await db.commit()
    return {"ok": True, "imported": len(entries)}


# ==== 正则脚本 ====


async def regex_list(db: AsyncSession, user_id: str) -> dict[str, Any]:
    rows = (
        (
            await db.execute(
                select(RegexScript)
                .where(RegexScript.user_id == user_id)
                .order_by(RegexScript.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "pattern": r.pattern,
                "replacement": r.replacement,
                "placement": r.placement,
                "enabled": bool(r.enabled),
                "scope": r.scope,
                "character_name": r.character_name,
            }
            for r in rows
        ]
    }


async def regex_add(db: AsyncSession, user_id: str, req: Any) -> dict[str, Any]:
    row = RegexScript(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=req.name,
        pattern=req.pattern,
        replacement=req.replacement,
        placement=req.placement,
        enabled=req.enabled,
        scope=req.scope,
        character_name=req.character_name,
    )
    db.add(row)
    await db.commit()
    return {"ok": True, "id": row.id}


async def regex_update(
    db: AsyncSession,
    user_id: str,
    script_id: str,
    req: Any,
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(RegexScript).where(RegexScript.id == script_id, RegexScript.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="脚本不存在")
    row.name = req.name
    row.pattern = req.pattern
    row.replacement = req.replacement
    row.placement = req.placement
    row.enabled = req.enabled
    row.scope = req.scope
    row.character_name = req.character_name
    await db.commit()
    return {"ok": True}


async def regex_delete(db: AsyncSession, user_id: str, script_id: str) -> dict[str, Any]:
    row = (
        await db.execute(
            select(RegexScript).where(RegexScript.id == script_id, RegexScript.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="脚本不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ==== 快捷回复 ====


async def quick_replies_list(
    db: AsyncSession,
    user_id: str,
    character_name: str = "",
) -> dict[str, Any]:
    stmt = select(QuickReply).where(QuickReply.user_id == user_id)
    if character_name:
        stmt = stmt.where(
            (QuickReply.scope == "global") | (QuickReply.character_name == character_name)
        )
    else:
        stmt = stmt.where(QuickReply.scope == "global")
    stmt = stmt.order_by(QuickReply.sort_order.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "label": r.label,
                "message": r.message,
                "scope": r.scope,
                "character_name": r.character_name,
                "sort_order": r.sort_order,
                "auto": bool(r.auto),
            }
            for r in rows
        ]
    }


async def quick_replies_add(db: AsyncSession, user_id: str, req: Any) -> dict[str, Any]:
    row = QuickReply(
        id=str(uuid.uuid4()),
        user_id=user_id,
        label=req.label,
        message=req.message,
        scope=req.scope,
        character_name=req.character_name,
        sort_order=req.sort_order,
        auto=req.auto,
    )
    db.add(row)
    await db.commit()
    return {"ok": True, "id": row.id}


async def quick_replies_delete(db: AsyncSession, user_id: str, reply_id: str) -> dict[str, Any]:
    row = (
        await db.execute(
            select(QuickReply).where(QuickReply.id == reply_id, QuickReply.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="快捷回复不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ==== 用户形象 ====


async def personas_list(db: AsyncSession, user_id: str) -> dict[str, Any]:
    rows = (
        (
            await db.execute(
                select(RoleplayPersona)
                .where(RoleplayPersona.user_id == user_id)
                .order_by(RoleplayPersona.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "avatar_asset_id": p.avatar_asset_id,
            }
            for p in rows
        ]
    }


async def personas_add(db: AsyncSession, user_id: str, req: Any) -> dict[str, Any]:
    row = RoleplayPersona(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=req.name,
        description=req.description,
        avatar_asset_id=req.avatar_asset_id,
    )
    db.add(row)
    await db.commit()
    return {"ok": True, "id": row.id}


async def personas_delete(db: AsyncSession, user_id: str, persona_id: str) -> dict[str, Any]:
    row = (
        await db.execute(
            select(RoleplayPersona).where(
                RoleplayPersona.id == persona_id, RoleplayPersona.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="形象不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
