"""Personal Voice Engine 端点：文风档案读写 / 自动提取 / 个人语料管理。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.voice import VoiceProfile
from app.security.auth import get_current_user
from app.services import voice_service

router = APIRouter()


def _profile_dict(p: VoiceProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "voice_dna": p.voice_dna or {},
        "samples": p.samples or [],
        "source": p.source,
        "updated_at": (p.updated_at.isoformat() + "Z") if p.updated_at else None,
    }


@router.get("/profile")
async def get_profile(
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """读当前用户文风档案。"""
    p = await voice_service.get_profile(db, str(user.id))
    if not p:
        return {"exists": False}
    return {"exists": True, "profile": _profile_dict(p)}


class ProfileUpdateIn(BaseModel):
    name: str | None = Field(None, max_length=50)
    voice_dna: dict[str, Any] | None = None
    samples: list[dict[str, Any]] | None = None


@router.put("/profile")
async def update_profile(
    body: ProfileUpdateIn,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动编辑/建档文风（upsert；无档案则创建）。"""
    p = await voice_service.update_profile(
        db,
        str(user.id),
        name=body.name,
        dna=body.voice_dna,
        samples=body.samples,
    )
    return {"exists": True, "profile": _profile_dict(p)}


@router.post("/profile/extract")
async def extract_profile(
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """从个人语料自动提炼文风（LLM 辅助；无足够语料返回 ok:false）。"""
    p = await voice_service.auto_extract_profile(db, str(user.id))
    if p is None:
        return {"ok": False, "reason": "暂无语料：先粘贴几段你写的文字到「个人语料」，或等对话/文档积累"}
    return {"ok": True, "profile": _profile_dict(p)}


@router.delete("/profile")
async def delete_profile(
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除文风档案（停用 voice 注入）。"""
    res = await db.execute(
        delete(VoiceProfile).where(VoiceProfile.user_id == str(user.id))
    )
    await db.commit()
    return {"deleted": int(res.rowcount or 0)}


@router.get("/corpus")
async def list_corpus(
    kind: str | None = None,
    limit: int = 50,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """个人语料列表（新→旧）。"""
    items = await voice_service.list_corpus(db, str(user.id), kind=kind, limit=limit)
    return {"items": items}


class CorpusAddIn(BaseModel):
    kind: str = "note"
    text: str = Field(..., min_length=8)
    source_ref: str = ""


@router.post("/corpus")
async def add_corpus(
    body: CorpusAddIn,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新增一条个人语料（用户粘贴自己的真实文字作风格样本）。"""
    item = await voice_service.add_corpus(
        db, str(user.id), kind=body.kind, text=body.text, source_ref=body.source_ref
    )
    if item is None:
        return {"ok": False, "reason": "文本过短（至少 8 字）"}
    return {
        "ok": True,
        "item": {
            "id": item.id,
            "kind": item.kind,
            "text": item.text_snippet,
        },
    }
