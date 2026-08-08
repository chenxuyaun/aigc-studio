"""角色扮演端点（SillyTavern 功能融入版）：

角色卡（列表/详情/编辑/删除/导入/导出）、聊天（普通 + 流式 + 会话 CRUD + JSONL 导入导出）、
世界书（全字段 CRUD）、正则脚本、快捷回复、用户形象。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.quick_reply import QuickReply
from app.models.regex_script import RegexScript
from app.models.roleplay_character import RoleplayCharacter
from app.models.roleplay_chat import RoleplayChat
from app.models.roleplay_lore import RoleplayLoreEntry
from app.models.roleplay_persona import RoleplayPersona
from app.models.user import User
from app.security.auth import get_current_user
from app.services import sessions
from app.services.media_access import sign_content_url
from app.services.roleplay import list_characters, roleplay_chat, roleplay_chat_stream

router = APIRouter()


# ==== 请求模型 ====

class RoleplayChatRequest(BaseModel):
    character_asset_ids: list[str] = Field(max_length=20)
    messages: list[dict[str, str]] = Field(max_length=200)
    model: str = ""
    group: bool = False
    session_id: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    persona_id: str | None = None
    note: dict[str, Any] | None = None
    mode: str = "normal"  # normal / continue（续写）
    swipe: bool = False  # True = 生成备选回复（不落库）
    group_strategy: str = "natural"  # natural / list / random
    group_mode: str = "append"  # append（全员卡片）/ swap（仅说话者）


class LoreEntryRequest(BaseModel):
    character_name: str | None = None  # None = 全局书
    project_id: str | None = None  # 创作项目作用域（None = 常规角色扮演）
    keyword: str = Field(default="", max_length=200)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    keysecondary: list[str] = Field(default_factory=list)
    content: str = Field(default="", max_length=50_000)
    constant: bool = False
    selective: bool = True
    selective_logic: str = "AND_ANY"
    position: str = "before"
    order_value: int = 100
    depth: int = 4
    role: str = "system"
    scan_depth: int | None = None
    case_sensitive: bool = False
    match_whole_words: bool = False
    probability: int = 100
    enabled: bool = True


class ChatCreateRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    character_asset_ids: list[str] = Field(default_factory=list)
    group: bool = False
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    settings: dict[str, Any] | None = None


class ChatUpdateRequest(BaseModel):
    title: str | None = None
    clear: bool = False
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    remove_index: int | None = None  # 删除单条消息（按索引）


class RegexScriptRequest(BaseModel):
    name: str = ""
    pattern: str
    replacement: str = ""
    placement: str = "ai_output"
    enabled: bool = True
    scope: str = "global"
    character_name: str | None = None


class QuickReplyRequest(BaseModel):
    label: str
    message: str = ""
    scope: str = "global"
    character_name: str | None = None
    sort_order: int = 0
    auto: bool = False  # True = 用户消息后自动触发


class PersonaRequest(BaseModel):
    name: str
    description: str = ""
    avatar_asset_id: str | None = None


# ==== 辅助 ====

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
        "character_asset_ids": char_ids,
        "group": bool(c.group),
        "model": c.model,
        "temperature": c.temperature,
        "max_tokens": c.max_tokens,
        "top_p": c.top_p,
        "settings": settings,
        "message_count": len(sessions.chat_messages(c)),
        "created_at": str(c.created_at) if c.created_at else "",
        "updated_at": str(c.updated_at) if c.updated_at else "",
    }


# ==== 角色卡 ====

@router.get("/characters")
async def characters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """素材库中的角色卡列表。"""
    items = await list_characters(db, user.id)
    # 附角色名（从结构化行读，未同步的跳过）
    for it in items:
        row = await db.get(RoleplayCharacter, it["asset_id"])
        it["name"] = row.name if row else ""
    return {"items": items}


@router.get("/characters/{asset_id}")
async def character_detail(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """角色卡详情（全字段）。"""
    from app.models.asset import Asset

    asset = (
        await db.execute(
            select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id)
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    row = await db.get(RoleplayCharacter, asset_id)
    if row is None:
        # 懒同步：解析 PNG
        from app.services import roleplay as rp
        from app.storage import get_storage

        store = get_storage(asset.storage_backend)
        data = await store.get(asset.storage_key)
        card = rp.parse_character_png(data) if data else {}
        if not card:
            raise HTTPException(status_code=404, detail="角色卡内容解析失败")
        await rp._sync_character_row(db, user.id, asset_id, card)
        await db.commit()
        row = await db.get(RoleplayCharacter, asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="角色卡同步失败")
    return {"asset": {**_character_dict(row), "url": sign_content_url(str(asset_id))}}


@router.put("/characters/{asset_id}")
async def character_update(
    asset_id: str,
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """编辑角色卡字段（name/description/personality/scenario/first_mes/mes_example/…）。"""
    row = await db.get(RoleplayCharacter, asset_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    allowed = {
        "name", "description", "personality", "scenario", "first_mes", "mes_example",
        "alternate_greetings", "system_prompt", "post_history_instructions",
        "creator_notes", "tags", "character_book", "talkativeness", "depth_prompt", "settings",
    }
    for k, v in body.items():
        if k not in allowed:
            continue
        if k in ("alternate_greetings", "tags"):
            setattr(row, k, json.dumps(v if isinstance(v, list) else [], ensure_ascii=False))
        elif k in ("character_book", "depth_prompt", "settings"):
            setattr(row, k, json.dumps(v if isinstance(v, dict) else {}, ensure_ascii=False))
        elif k == "talkativeness":
            row.talkativeness = float(v or 0.5)
        else:
            setattr(row, k, str(v or ""))
    await db.commit()
    return {"ok": True, "asset_id": asset_id}


@router.delete("/characters/{asset_id}")
async def character_delete(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除角色卡（资产 + 结构化行）。"""
    from app.models.asset import Asset

    asset = (
        await db.execute(
            select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id)
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    from app.storage import get_storage

    store = get_storage(asset.storage_backend)
    import contextlib

    with contextlib.suppress(Exception):
        await store.delete(asset.storage_key)
    row = await db.get(RoleplayCharacter, asset_id)
    if row is not None:
        await db.delete(row)
    await db.delete(asset)
    await db.commit()
    return {"ok": True}


@router.post("/characters/import")
async def character_import(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """导入角色卡：PNG（V1/V2/V3）或 JSON 文件 → 入库。"""
    from app.models.asset import Asset
    from app.services.character_card import import_character_card

    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大（>10MB）")
    result = import_character_card(data)
    if not result:
        raise HTTPException(
            status_code=400, detail="无法解析角色卡（支持 PNG chara/ccv3 或 V1/V2/V3 JSON）"
        )
    card, png = result["card"], result["png"]
    asset_id = str(uuid.uuid4())
    asset = Asset(
        id=asset_id,
        user_id=user.id,
        filename=f"character-{asset_id[:8]}.png",
        mime_type="image/png",
        storage_backend="local",
        storage_key=f"roleplay/{asset_id[:8]}.png",
    )
    db.add(asset)
    from app.storage import get_storage

    store = get_storage("local")
    await store.put(asset.storage_key, png)
    from app.services.roleplay import _sync_character_row

    await _sync_character_row(db, user.id, asset_id, card)
    await db.commit()
    return {
        "ok": True,
        "asset_id": asset_id,
        "name": card.get("name", ""),
        "source": result["source"],
    }


@router.get("/characters/{asset_id}/export")
async def character_export(
    asset_id: str,
    format: str = Query("png"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """导出角色卡：png（重打包）或 json（V2）。"""
    from app.models.asset import Asset
    from app.services.character_card import export_character_card
    from app.storage import get_storage

    asset = (
        await db.execute(
            select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id)
        )
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    store = get_storage(asset.storage_backend)
    try:
        png = await store.get(asset.storage_key)
    except Exception:
        png = None
    row = await db.get(RoleplayCharacter, asset_id)
    card = _character_dict(row) if row else {}
    if not card:
        from app.services.roleplay import parse_character_png
        card = parse_character_png(png or b"")
    # 剥离内部字段，避免写进 V2 角色卡 JSON
    card = {k: v for k, v in card.items() if k not in ("asset_id", "url")}
    body, mime = export_character_card(png, card, format)
    return Response(
        content=body,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="character-{asset_id[:8]}.{format}"'
        },
    )


# ==== 聊天 ====

@router.post("/chat")
async def chat(
    req: RoleplayChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """角色扮演对话（单角色 / 群聊 + 情绪标注 + 会话落库）。"""
    result = await roleplay_chat(
        db,
        user.id,
        req.character_asset_ids,
        req.messages,
        req.model,
        req.group,
        session_id=req.session_id,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        top_p=req.top_p,
        persona_id=req.persona_id,
        note=req.note,
        mode=req.mode,
        swipe=req.swipe,
        group_strategy=req.group_strategy,
        group_mode=req.group_mode,
    )
    await db.commit()
    return result


@router.post("/chat/stream")
async def chat_stream(
    req: RoleplayChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """角色扮演流式对话（SSE）。"""

    from collections.abc import AsyncIterator

    async def _gen() -> AsyncIterator[str]:
        async for ev in roleplay_chat_stream(
            db,
            user.id,
            req.character_asset_ids,
            req.messages,
            req.model,
            req.group,
            session_id=req.session_id,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            top_p=req.top_p,
            persona_id=req.persona_id,
            note=req.note,
            group_strategy=req.group_strategy,
            group_mode=req.group_mode,
        ):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if ev.get("type") == "done":
                await db.commit()
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/chats")
async def chats_list(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """会话列表（不含消息内容）。"""
    rows = await sessions.list_chats(db, user.id)
    return {"items": [_chat_dict(c) for c in rows]}


@router.post("/chats")
async def chats_create(
    req: ChatCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新建会话。"""
    chat = await sessions.create_chat(
        db,
        user.id,
        title=req.title,
        character_asset_ids=req.character_asset_ids,
        group=req.group,
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        top_p=req.top_p,
        settings=req.settings,
    )
    await db.commit()
    await db.refresh(chat)
    return {"ok": True, "chat": _chat_dict(chat)}


@router.get("/chats/{chat_id}")
async def chats_get(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """会话详情（含全部消息）。"""
    chat = await sessions.get_chat(db, user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"chat": _chat_dict(chat), "messages": sessions.chat_messages(chat)}


@router.put("/chats/{chat_id}")
async def chats_update(
    chat_id: str,
    req: ChatUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """重命名 / 清空 / 更新模型与采样参数。"""
    chat = await sessions.get_chat(db, user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if req.clear:
        chat.messages = "[]"
    if req.remove_index is not None:
        sessions.remove_message(chat, req.remove_index)
    if req.title is not None:
        chat.title = req.title
    if req.model is not None:
        chat.model = req.model
    if req.temperature is not None:
        chat.temperature = req.temperature
    if req.max_tokens is not None:
        chat.max_tokens = req.max_tokens
    if req.top_p is not None:
        chat.top_p = req.top_p
    await db.commit()
    return {"ok": True}


@router.post("/chats/{chat_id}/branch")
async def chats_branch(
    chat_id: str,
    index: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """从第 index 条消息（含）分叉新会话。"""
    chat = await sessions.get_chat(db, user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    branch = await sessions.branch_chat(db, user.id, chat, index)
    if branch is None:
        raise HTTPException(status_code=400, detail="消息索引越界")
    await db.commit()
    await db.refresh(branch)
    return {"ok": True, "chat": _chat_dict(branch)}


@router.delete("/chats/{chat_id}")
async def chats_delete(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    chat = await sessions.get_chat(db, user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    await sessions.delete_chat(db, chat)
    await db.commit()
    return {"ok": True}


@router.get("/chats/{chat_id}/export")
async def chats_export(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """导出会话为 SillyTavern JSONL。"""
    chat = await sessions.get_chat(db, user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    content = sessions.export_jsonl(chat)
    return Response(
        content=content.encode("utf-8"),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="chat-{chat_id[:8]}.jsonl"'
        },
    )


@router.post("/chats/import")
async def chats_import(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """导入 SillyTavern JSONL 会话。"""
    data = (await file.read()).decode("utf-8", errors="replace")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大（>5MB）")
    chat = sessions.import_jsonl(db, user.id, data)
    if chat is None:
        raise HTTPException(status_code=400, detail="无法解析 JSONL（首行应为 metadata JSON）")
    await db.commit()
    await db.refresh(chat)
    return {"ok": True, "chat": _chat_dict(chat)}


# ==== 世界书 ====

@router.get("/lore")
async def list_lore(
    character_name: str = "",
    project_id: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """世界书条目列表（全字段；project_id 过滤创作项目作用域）。"""
    stmt = select(RoleplayLoreEntry).where(RoleplayLoreEntry.user_id == user.id)
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


@router.post("/lore")
async def add_lore(
    req: LoreEntryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新增世界书条目（全字段）。"""
    keywords = req.keywords or ([req.keyword] if req.keyword else [])
    entry = RoleplayLoreEntry(
        id=str(uuid.uuid4()),
        user_id=user.id,
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


@router.put("/lore/{entry_id}")
async def update_lore(
    entry_id: str,
    req: LoreEntryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """编辑世界书条目。"""
    entry = (
        await db.execute(
            select(RoleplayLoreEntry).where(
                RoleplayLoreEntry.id == entry_id,
                RoleplayLoreEntry.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="条目不存在或无权访问")
    keywords = req.keywords or ([req.keyword] if req.keyword else [])
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


@router.delete("/lore/{entry_id}")
async def delete_lore(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除世界书条目。"""
    entry = (
        await db.execute(
            select(RoleplayLoreEntry).where(
                RoleplayLoreEntry.id == entry_id,
                RoleplayLoreEntry.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="条目不存在或无权访问")
    await db.delete(entry)
    await db.commit()
    return {"ok": True}


# ==== 世界书导入导出（SillyTavern lorebook 互通） ====

@router.get("/lore/export")
async def lore_export(
    character_name: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """导出世界书为 SillyTavern lorebook JSON（可按角色过滤）。"""
    from app.services.worldbook import lorebook_to_st

    stmt = select(RoleplayLoreEntry).where(RoleplayLoreEntry.user_id == user.id)
    if character_name:
        stmt = stmt.where(RoleplayLoreEntry.character_name == character_name)
    rows = (await db.execute(stmt)).scalars().all()
    book = lorebook_to_st(list(rows), "AIGC 角色扮演世界书")
    return Response(
        content=json.dumps(book, ensure_ascii=False, indent=2).encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="lorebook.json"'},
    )


@router.post("/lore/import")
async def lore_import(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """导入 SillyTavern lorebook JSON → 世界书条目（character_name 为空 = 全局书）。"""
    from app.services.worldbook import lorebook_from_st

    data = (await file.read()).decode("utf-8", errors="replace")
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
            user_id=user.id,
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

@router.get("/regex-scripts")
async def regex_list(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(RegexScript)
            .where(RegexScript.user_id == user.id)
            .order_by(RegexScript.created_at.asc())
        )
    ).scalars().all()
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


@router.post("/regex-scripts")
async def regex_create(
    req: RegexScriptRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = RegexScript(
        id=str(uuid.uuid4()),
        user_id=user.id,
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


@router.put("/regex-scripts/{script_id}")
async def regex_update(
    script_id: str,
    req: RegexScriptRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(RegexScript).where(
                RegexScript.id == script_id, RegexScript.user_id == user.id
            )
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


@router.delete("/regex-scripts/{script_id}")
async def regex_delete(
    script_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(RegexScript).where(
                RegexScript.id == script_id, RegexScript.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="脚本不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ==== 快捷回复 ====

@router.get("/quick-replies")
async def quick_replies_list(
    character_name: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(QuickReply).where(QuickReply.user_id == user.id)
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


@router.post("/quick-replies")
async def quick_replies_create(
    req: QuickReplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = QuickReply(
        id=str(uuid.uuid4()),
        user_id=user.id,
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


@router.delete("/quick-replies/{reply_id}")
async def quick_replies_delete(
    reply_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(QuickReply).where(
                QuickReply.id == reply_id, QuickReply.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="快捷回复不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ==== 用户形象 ====

@router.get("/personas")
async def personas_list(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(RoleplayPersona)
            .where(RoleplayPersona.user_id == user.id)
            .order_by(RoleplayPersona.created_at.asc())
        )
    ).scalars().all()
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


@router.post("/personas")
async def personas_create(
    req: PersonaRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = RoleplayPersona(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=req.name,
        description=req.description,
        avatar_asset_id=req.avatar_asset_id,
    )
    db.add(row)
    await db.commit()
    return {"ok": True, "id": row.id}


@router.delete("/personas/{persona_id}")
async def personas_delete(
    persona_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(RoleplayPersona).where(
                RoleplayPersona.id == persona_id, RoleplayPersona.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="形象不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
