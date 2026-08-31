"""Core Runtime - Roleplay 角色卡资产编排（P1-2 从 api/v1/roleplay.py 抽离，逐字搬运）。

角色卡 = Asset（PNG 存储）+ RoleplayCharacter（结构化行）双载体：
- 列表（素材库 + 角色名批量回填）/ 详情（懒同步：首次访问解析 PNG 补建结构化行）
- 字段编辑（白名单 + JSON 字段序列化）/ 删除（存储 + 双行）
- 导入（PNG V1/V2/V3 或 JSON → Asset 入库 + 结构化行同步）/ 导出（png 重打包 / V2 JSON）

说明：HTTPException 用法沿用 core.runtime.asset.access 的既有先例（helper 抛 4xx，路由直传）。
"""
from __future__ import annotations

import contextlib
import uuid
from typing import Any

from app.core.runtime.asset.access import sign_content_url
from app.core.runtime.roleplay.serializers import _character_dict
from app.models.asset import Asset
from app.models.roleplay_character import RoleplayCharacter
from app.models.user import User
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_character_cards(db: AsyncSession, user: User) -> dict[str, Any]:
    """素材库中的角色卡列表（附角色名，批量 IN 取行避免 N+1）。"""
    from app.services.roleplay import list_characters

    items = await list_characters(db, user.id)
    ids = [it["asset_id"] for it in items]
    if ids:
        rows = {
            r.asset_id: r.name
            for r in (
                await db.execute(
                    select(RoleplayCharacter).where(RoleplayCharacter.asset_id.in_(ids))
                )
            )
            .scalars()
            .all()
        }
    else:
        rows = {}
    for it in items:
        it["name"] = rows.get(it["asset_id"], "")
    return {"items": items}


async def character_detail(db: AsyncSession, user: User, asset_id: str) -> dict[str, Any]:
    """角色卡详情（全字段）。懒同步：结构化行缺失时解析 PNG 补建。"""
    from app.storage import get_storage

    asset = (
        await db.execute(select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    row = await db.get(RoleplayCharacter, asset_id)
    if row is None:
        # 懒同步：解析 PNG
        from app.services import roleplay as rp

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


_CHARACTER_EDITABLE_FIELDS = {
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "alternate_greetings",
    "system_prompt",
    "post_history_instructions",
    "creator_notes",
    "tags",
    "character_book",
    "talkativeness",
    "depth_prompt",
    "settings",
}


async def character_update_fields(
    db: AsyncSession,
    user: User,
    asset_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """编辑角色卡字段（name/description/personality/scenario/first_mes/mes_example/…）。"""
    row = await db.get(RoleplayCharacter, asset_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    import json

    for k, v in body.items():
        if k not in _CHARACTER_EDITABLE_FIELDS:
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


async def character_delete(db: AsyncSession, user: User, asset_id: str) -> dict[str, Any]:
    """删除角色卡（资产 + 结构化行 + 存储对象尽力删）。"""
    from app.storage import get_storage

    asset = (
        await db.execute(select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    store = get_storage(asset.storage_backend)
    with contextlib.suppress(Exception):
        await store.delete(asset.storage_key)
    row = await db.get(RoleplayCharacter, asset_id)
    if row is not None:
        await db.delete(row)
    await db.delete(asset)
    await db.commit()
    return {"ok": True}


async def character_import(db: AsyncSession, user: User, data: bytes) -> dict[str, Any]:
    """导入角色卡：PNG（V1/V2/V3）或 JSON 文件 → 入库。"""
    from app.services.character_card import import_character_card
    from app.storage import get_storage

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


async def character_export(
    db: AsyncSession,
    user: User,
    asset_id: str,
    fmt: str,
) -> tuple[bytes, str]:
    """导出角色卡：png（重打包）或 json（V2）。返回 (body, mime)，文件名由路由拼。"""
    from app.services.character_card import export_character_card
    from app.storage import get_storage

    asset = (
        await db.execute(select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id))
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
    return export_character_card(png, card, fmt)
