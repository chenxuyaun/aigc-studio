"""角色陪伴记忆：原著蒸馏触发/状态 + 交互记忆总览/清空 + 注入配置。

交互记忆（L0-L3）存于 MemoryCore gateway，本模块经 memory_client 封装访问；
原著蒸馏档案存 character_profiles 表。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.character_profile import CharacterProfile
from app.models.roleplay_character import RoleplayCharacter
from app.models.user import User
from app.security.auth import get_current_user
from app.services import memory_client
from app.tasks.distill_tasks import _dispatch_distill

router = APIRouter(tags=["memory"])

# 角色卡 settings JSON 中的记忆配置段
_MEMORY_SETTINGS_KEY = "memory"


def _profile_dict(p: CharacterProfile) -> dict[str, Any]:
    return {
        "asset_id": p.asset_id,
        "book_title": p.book_title,
        "source_doc_id": p.source_doc_id,
        "identity": p.identity,
        "personality": p.personality,
        "speech_style": p.speech_style,
        "knowledge_bounds": p.knowledge_bounds,
        "relationships": _load_json(p.relationships, []),
        "core_memories": _load_json(p.core_memories, []),
        "status": p.status,
        "error": p.error,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _load_json(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except Exception:
        return default


def _memory_config(row: RoleplayCharacter) -> dict[str, Any]:
    settings = _load_json(row.settings, {})
    cfg = (settings.get(_MEMORY_SETTINGS_KEY) or {}) if isinstance(settings, dict) else {}
    return {
        "inject": bool(cfg.get("inject", True)),
        "budget": int(cfg.get("budget", 2500)),
    }


def _set_memory_config(row: RoleplayCharacter, cfg: dict[str, Any]) -> None:
    settings = _load_json(row.settings, {})
    if not isinstance(settings, dict):
        settings = {}
    settings[_MEMORY_SETTINGS_KEY] = cfg
    row.settings = json.dumps(settings, ensure_ascii=False)


async def _get_character(
    db: AsyncSession, user_id: str, asset_id: str
) -> RoleplayCharacter:
    row = await db.get(RoleplayCharacter, asset_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    return row


class DistillRequest(BaseModel):
    asset_id: str
    doc_id: str | None = None
    text: str | None = None
    book_title: str | None = None


@router.post("/memory/distill")
async def trigger_distill(
    body: DistillRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """触发原著蒸馏（书籍文本 → 角色档案，后台任务执行）。"""
    row = await _get_character(db, user.id, body.asset_id)
    if not body.doc_id and not (body.text or "").strip():
        raise HTTPException(status_code=400, detail="需要提供知识库文档或直接粘贴文本")

    profile = (
        await db.execute(
            select(CharacterProfile).where(
                CharacterProfile.asset_id == body.asset_id,
                CharacterProfile.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        profile = CharacterProfile(
            asset_id=body.asset_id,
            user_id=user.id,
            source_doc_id=body.doc_id,
            book_title=body.book_title or row.name,
        )
        db.add(profile)
    else:
        profile.source_doc_id = body.doc_id
        if body.book_title:
            profile.book_title = body.book_title
    profile.status = "pending"
    profile.error = ""
    await db.commit()

    _dispatch_distill(
        user.id, body.asset_id, doc_id=body.doc_id, text=body.text, book_title=body.book_title
    )
    return {"ok": True, "asset_id": body.asset_id, "status": "pending"}


@router.get("/memory/distill/{asset_id}")
async def distill_status(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """蒸馏状态（前端轮询用）。"""
    await _get_character(db, user.id, asset_id)
    profile = (
        await db.execute(
            select(CharacterProfile).where(
                CharacterProfile.asset_id == asset_id,
                CharacterProfile.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        return {"asset_id": asset_id, "status": "none"}
    return _profile_dict(profile)


@router.get("/memory/{asset_id}")
async def memory_overview(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """记忆总览：原著档案 + 交互记忆（L1 最近 / L2 场景 / L3 画像）+ 注入配置。"""
    row = await _get_character(db, user.id, asset_id)
    profile = (
        await db.execute(
            select(CharacterProfile).where(
                CharacterProfile.asset_id == asset_id,
                CharacterProfile.user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    # 交互记忆（gateway 可能不可用 → 空列表，不影响总览）
    atoms, scenarios, persona = await _load_interactive_memory(user.id, asset_id)

    return {
        "asset_id": asset_id,
        "profile": _profile_dict(profile) if profile else None,
        "atoms": atoms,
        "scenarios": scenarios,
        "persona": persona,
        "config": _memory_config(row),
    }


async def _load_interactive_memory(
    user_id: str, asset_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    from app.services.memory_client import (
        memory_list_scenarios,
        memory_query_atomic,
        memory_read_core,
    )

    atoms_result = await memory_query_atomic(user_id, asset_id, limit=20)
    atoms: list[dict[str, Any]] = []
    for a in atoms_result:
        if isinstance(a, dict) and a.get("content"):
            atoms.append(
                {
                    "id": a.get("id"),
                    "content": str(a.get("content"))[:300],
                    "type": a.get("type") or "",
                    "scene": a.get("scene_name") or "",
                    "priority": a.get("priority"),
                    "created_at": a.get("created_at") or a.get("timestamps") or "",
                }
            )
    return (
        atoms,
        await memory_list_scenarios(user_id, asset_id),
        await memory_read_core(user_id, asset_id),
    )


@router.post("/memory/{asset_id}/clear")
async def memory_clear(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """清空该角色的交互记忆（L0-L3）。"""
    await _get_character(db, user.id, asset_id)
    await memory_client.memory_clear(user.id, asset_id)
    return {"ok": True, "asset_id": asset_id}


@router.get("/memory/{asset_id}/config")
async def memory_config_get(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await _get_character(db, user.id, asset_id)
    return {"asset_id": asset_id, "config": _memory_config(row)}


class MemoryConfigRequest(BaseModel):
    inject: bool = True
    budget: int = 2500


@router.put("/memory/{asset_id}/config")
async def memory_config_put(
    asset_id: str,
    body: MemoryConfigRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """注入开关与预算（存角色卡 settings.memory）。"""
    row = await _get_character(db, user.id, asset_id)
    _set_memory_config(
        row, {"inject": bool(body.inject), "budget": max(500, min(8000, int(body.budget)))}
    )
    await db.commit()
    return {"ok": True, "asset_id": asset_id, "config": _memory_config(row)}
