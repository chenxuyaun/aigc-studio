"""社区分享墙端点（批11）：发布 / 墙 / 点赞 toggle / 删除（仅作者）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.community_post import CommunityPost
from app.security.auth import get_current_user

router = APIRouter()


class PostIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=4000)
    kind: str = Field(default="text", pattern="^(text|image)$")
    image_url: str = Field(default="", max_length=500)


@router.post("/posts")
async def create_post(
    body: PostIn,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.kind == "image" and not body.image_url.strip():
        raise HTTPException(status_code=422, detail="图片帖必须带 image_url")
    row = CommunityPost(
        user_id=str(user.id),
        author_name=(getattr(user, "username", "") or "创作者")[:60],
        title=body.title.strip(),
        content=body.content.strip(),
        kind=body.kind,
        image_url=body.image_url.strip(),
    )
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.get("/posts")
async def list_posts(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=50),
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    total = (
        await db.execute(select(func.count()).select_from(CommunityPost))
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(CommunityPost)
                .order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    uid = str(user.id)
    return {
        "items": [
            {
                "id": r.id,
                "author_name": r.author_name,
                "title": r.title,
                "content": r.content,
                "kind": r.kind,
                "image_url": r.image_url,
                "likes": r.likes,
                "liked_by_me": uid in (r.liked_by or []),
                "mine": r.user_id == uid,
                "created_at": (r.created_at.isoformat() + "Z") if r.created_at else None,
            }
            for r in rows
        ],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


@router.post("/posts/{post_id}/like")
async def toggle_like(
    post_id: str,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="帖子不存在")
    liked_by = list(row.liked_by or [])
    uid = str(user.id)
    if uid in liked_by:
        liked_by.remove(uid)
        row.likes = max(0, int(row.likes or 0) - 1)
        liked = False
    else:
        liked_by.append(uid)
        row.likes = int(row.likes or 0) + 1
        liked = True
    row.liked_by = liked_by
    await db.commit()
    return {"likes": row.likes, "liked": liked}


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: str,
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(select(CommunityPost).where(CommunityPost.id == post_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="帖子不存在")
    if row.user_id != str(user.id):
        raise HTTPException(status_code=403, detail="只能删除自己的分享")
    await db.delete(row)
    await db.commit()
    return {"deleted": True}
