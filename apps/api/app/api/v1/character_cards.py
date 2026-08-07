"""角色卡工厂端点。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.asset import Asset
from app.models.user import User
from app.security.auth import get_current_user
from app.storage import choose_write_backend, get_storage

router = APIRouter()


class CharacterCardRequest(BaseModel):
    description: str = Field(min_length=2)
    style: str = "动漫"


@router.post("/generate")
async def generate_character_card(
    req: CharacterCardRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """生成角色卡并入库素材库。"""
    from app.services.character_card import generate_character_card as _gen

    result = await _gen(db, req.description, req.style)
    card = result["card"]
    png = result["png"]
    now = datetime.now(UTC)
    task_id = str(uuid.uuid4())
    key = f"{user.id}/{now:%Y/%m}/{task_id}-character.png"
    backend = choose_write_backend(user.id)
    store = get_storage(backend)
    await store.put(key, png, "image/png")
    asset = Asset(
        filename=f"character-{task_id[:8]}.png",
        storage_key=key,
        storage_backend=backend,
        mime_type="image/png",
        size_bytes=len(png),
        sha256=hashlib.sha256(png).hexdigest(),
        user_id=user.id,
        task_id=None,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return {
        "asset_id": asset.id,
        "url": f"/api/v1/assets/{asset.id}/content",
        "character": card,
    }
