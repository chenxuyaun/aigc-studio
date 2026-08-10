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
from app.services.director_assistant import director_chat_reply, is_director_cmd
from app.services.media_access import sign_content_url
from app.services.music_assistant import is_music_cmd, music_chat_reply
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
    author: str = ""  # 多人房间：真人身份名（消息以【身份】前缀参与群聊）
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
    is_room: bool = False  # 多人同场演出：全员可见可加入
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


class StatusBookUpdateRequest(BaseModel):
    """状态账本整本覆盖：{角色名: {类别: 当前值}}。"""

    book: dict[str, dict[str, str]] = Field(default_factory=dict)


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
        "is_room": bool(c.is_room),
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

@router.put("/characters/{asset_id}/share")
async def toggle_character_share(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """多人创作共享开关（仅 admin）：共享后全员可见可用该角色卡。"""
    from app.models.roleplay_character import RoleplayCharacter

    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可设置共享")
    row = (
        await db.execute(
            select(RoleplayCharacter).where(RoleplayCharacter.asset_id == asset_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    row.is_shared = not row.is_shared
    await db.commit()
    return {"asset_id": asset_id, "is_shared": row.is_shared}


@router.get("/characters")
async def characters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """素材库中的角色卡列表。"""
    items = await list_characters(db, user.id)
    # 附角色名（批量 IN 取结构化行，未同步的跳过；原逐行 db.get N+1）
    ids = [it["asset_id"] for it in items]
    if ids:
        rows = {
            r.asset_id: r.name
            for r in (
                await db.execute(
                    select(RoleplayCharacter).where(RoleplayCharacter.asset_id.in_(ids))
                )
            ).scalars().all()
        }
    else:
        rows = {}
    for it in items:
        it["name"] = rows.get(it["asset_id"], "")
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

async def _music_cmd_result(
    db: AsyncSession,
    user_id: str,
    req: RoleplayChatRequest,
) -> dict[str, Any] | None:
    """群聊「@AI 写歌」指令拦截：命中返回音乐助手结果，否则 None。"""
    if not req.session_id or not req.messages:
        return None
    last = req.messages[-1]
    if last.get("role") != "user" or not is_music_cmd(last.get("content", "")):
        return None
    chat = await sessions.get_chat(db, user_id, req.session_id)
    if chat is None or not chat.is_room:
        return None
    return await music_chat_reply(db, user_id, chat, req.messages)


async def _director_cmd_result(
    db: AsyncSession,
    user_id: str,
    req: RoleplayChatRequest,
) -> dict[str, Any] | None:
    """群聊「@AI 导演」指令拦截：命中返回导演结果，否则 None。"""
    if not req.session_id or not req.messages:
        return None
    last = req.messages[-1]
    if last.get("role") != "user" or not is_director_cmd(last.get("content", "")):
        return None
    chat = await sessions.get_chat(db, user_id, req.session_id)
    if chat is None or not chat.is_room:
        return None
    return await director_chat_reply(db, user_id, chat, req.messages)


@router.post("/chat")
async def chat(
    req: RoleplayChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """角色扮演对话（单角色 / 群聊 + 情绪标注 + 会话落库）。"""
    # 群聊指令：@AI 写歌 / @AI 导演 → 群内助手（歌词创作 / 演出调度），群成员可见可继续 @
    music = await _music_cmd_result(db, user.id, req)
    if music is not None:
        await db.commit()
        return music
    director = await _director_cmd_result(db, user.id, req)
    if director is not None:
        await db.commit()
        return director
    # 多人房间：真人以 author 身份发言（【身份】前缀，AI 群聊可区分真人）
    if req.author.strip() and req.session_id:
        chat = await sessions.get_chat(db, user.id, req.session_id)
        if chat is not None and chat.is_room:
            req.messages = [
                {
                    **m,
                    "content": f"【{req.author.strip()}】{m.get('content', '')}"
                    if m.get("role") == "user"
                    else m.get("content", ""),
                }
                for m in req.messages
            ]
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
        # 群聊指令：@AI 写歌 / @AI 导演 → 助手整段返回（非流式生成，一次性发全）
        music = await _music_cmd_result(db, user.id, req)
        if music is not None:
            await db.commit()
            if music.get("error"):
                err = json.dumps({"type": "error", "error": music["error"]}, ensure_ascii=False)
                yield f"data: {err}\n\n"
            else:
                done = json.dumps(
                    {
                        "type": "done",
                        "reply": music["reply"],
                        "mood": "",
                        "mood_delta": 0,
                        "character": music.get("character"),
                        "model": music.get("model"),
                        "chat_id": music.get("chat_id"),
                        "worldbook_hits": 0,
                    },
                    ensure_ascii=False,
                )
                chunk = json.dumps(
                    {"type": "chunk", "content": music["reply"]}, ensure_ascii=False
                )
                yield f"data: {chunk}\n\n"
                yield f"data: {done}\n\n"
            yield "data: [DONE]\n\n"
            return
        director = await _director_cmd_result(db, user.id, req)
        if director is not None:
            await db.commit()
            if director.get("error"):
                err = json.dumps(
                    {"type": "error", "error": director["error"]}, ensure_ascii=False
                )
                yield f"data: {err}\n\n"
            else:
                done = json.dumps(
                    {
                        "type": "done",
                        "reply": director["reply"],
                        "mood": "",
                        "mood_delta": 0,
                        "character": director.get("character"),
                        "model": director.get("model"),
                        "chat_id": director.get("chat_id"),
                        "worldbook_hits": 0,
                    },
                    ensure_ascii=False,
                )
                chunk = json.dumps(
                    {"type": "chunk", "content": director["reply"]}, ensure_ascii=False
                )
                yield f"data: {chunk}\n\n"
                yield f"data: {done}\n\n"
            yield "data: [DONE]\n\n"
            return
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
        is_room=req.is_room,
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        top_p=req.top_p,
        settings=req.settings,
    )
    await db.commit()
    await db.refresh(chat)
    return {"ok": True, "chat": _chat_dict(chat)}


@router.post("/chats/{chat_id}/join")
async def chats_join(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """加入多人房间会话（返回会话+全部消息）；完整群需成员身份。"""
    from app.services import group_service

    chat = await sessions.get_chat(db, user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if chat.is_room:
        group = await group_service.get_group(db, chat_id)
        if group is not None and not await group_service.is_member(db, chat_id, user.id):
            raise HTTPException(status_code=403, detail="请先用邀请码加入群")
    return {"chat": _chat_dict(chat), "messages": sessions.chat_messages(chat)}


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


@router.get("/chats/{chat_id}/status-book")
async def chat_status_book_get(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查看会话状态账本（角色状态登记，跨对话保持一致）。"""
    chat = await sessions.get_chat(db, user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        settings = json.loads(chat.settings or "{}")
    except Exception:
        settings = {}
    return {"book": settings.get("status_book") or {}}


@router.put("/chats/{chat_id}/status-book")
async def chat_status_book_put(
    chat_id: str,
    req: StatusBookUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动校正状态账本（整本覆盖，如「伤势=已恢复」）。"""
    chat = await sessions.get_chat(db, user.id, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    from app.services.status_book import merge_settings

    try:
        settings = json.loads(chat.settings or "{}")
    except Exception:
        settings = {}
    chat.settings = json.dumps(merge_settings(settings, req.book), ensure_ascii=False)
    await db.commit()
    return {"ok": True, "book": req.book}


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


# ==== 完整群（多人创作） ====

class GroupCreateRequest(BaseModel):
    """建群：创建 is_room 会话 + 群资料。"""

    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=500)
    character_asset_ids: list[str] = Field(default_factory=list, max_length=20)
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None


class GroupJoinRequest(BaseModel):
    invite_code: str = Field(min_length=4, max_length=12)


class GroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    reset_invite: bool = False


@router.post("/groups", response_model=None)
async def groups_create(
    req: GroupCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """建群：is_room 会话 + 群资料 + 群主自动入群。"""
    from app.services import group_service

    chat = await sessions.create_chat(
        db, user.id,
        title=req.title or "新群",
        character_asset_ids=req.character_asset_ids or [],
        group=len(req.character_asset_ids) > 1,
        is_room=True,
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )
    group = await group_service.create_group(
        db, owner_id=user.id, chat_id=chat.id,
        name=req.title or "新群", description=req.description,
    )
    await db.commit()
    await db.refresh(chat)
    members = await group_service.list_members(db, chat.id)
    usernames = {user.id: user.username}
    return {
        "ok": True,
        "chat": _chat_dict(chat),
        "group": group_service.group_dict(group, members, usernames),
    }


@router.get("/groups/{chat_id}")
async def groups_detail(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """群详情：资料 + 成员列表（成员可见）。"""
    from app.models.user import User as UserModel
    from app.services import group_service

    group = await group_service.get_group(db, chat_id)
    if group is None:
        raise HTTPException(status_code=404, detail="群不存在")
    if not await group_service.is_member(db, chat_id, user.id) and user.role != "admin":
        raise HTTPException(status_code=403, detail="非群成员")
    members = await group_service.list_members(db, chat_id)
    ids = [m.user_id for m in members]
    usernames = {}
    if ids:
        rows = (await db.execute(select(UserModel).where(UserModel.id.in_(ids)))).scalars().all()
        usernames = {u.id: u.username for u in rows}
    return group_service.group_dict(group, members, usernames)


@router.post("/groups/join")
async def groups_join_code(
    req: GroupJoinRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """邀请码加入群。"""
    from app.services import group_service

    group, err = await group_service.join_by_code(db, req.invite_code.strip(), user.id)
    if group is None:
        raise HTTPException(status_code=404, detail=err)
    await db.commit()
    return {"ok": True, "chat_id": group.chat_id, "name": group.name}


@router.delete("/groups/{chat_id}/members/{target_user_id}")
async def groups_kick(
    chat_id: str,
    target_user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """群主踢人 / 成员退出。"""
    from app.services import group_service

    ok, err = await group_service.remove_member(db, chat_id, target_user_id, actor_id=user.id)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    await db.commit()
    return {"ok": True}


@router.put("/groups/{chat_id}")
async def groups_update(
    chat_id: str,
    req: GroupUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """群主修改资料 / 重置邀请码。"""
    from app.services import group_service

    group, err = await group_service.update_group(
        db, chat_id, actor_id=user.id,
        name=req.name, description=req.description, reset_invite=req.reset_invite,
    )
    if group is None:
        raise HTTPException(status_code=400, detail=err)
    await db.commit()
    members = await group_service.list_members(db, chat_id)
    return {"ok": True, "group": group_service.group_dict(group, members, {})}
