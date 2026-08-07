from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.photo import Photo
from app.models.photo_album import PhotoAlbum
from app.models.user import User
from app.schemas.generation import ImageGenerationRequest, TaskResponse
from app.security.auth import get_current_user
from app.services.generation_service import create_media_task

router = APIRouter()


async def _assert_reference_access(
    db: AsyncSession, user: User, req: ImageGenerationRequest
) -> None:
    """校验参考图归属：无权或不存在统一 400（避免枚举相册内容）。"""
    if req.reference_photo_id:
        photo = (
            await db.execute(select(Photo).where(Photo.id == req.reference_photo_id))
        ).scalar_one_or_none()
        if not photo:
            raise HTTPException(status_code=400, detail="参考照片不存在或无权使用")
        album = (
            await db.execute(select(PhotoAlbum).where(PhotoAlbum.id == photo.album_id))
        ).scalar_one_or_none()
        if not album:
            raise HTTPException(status_code=400, detail="参考照片不存在或无权使用")
        can = album.is_public or album.owner_id == user.id or user.role == "admin"
        if not can:
            raise HTTPException(status_code=400, detail="参考照片不存在或无权使用")

    if req.reference_asset_id:
        from app.models.asset import Asset

        asset = (
            await db.execute(select(Asset).where(Asset.id == req.reference_asset_id))
        ).scalar_one_or_none()
        if not asset or (asset.user_id != user.id and user.role != "admin"):
            raise HTTPException(status_code=400, detail="参考素材不存在或无权使用")


@router.post("/generate", response_model=TaskResponse)
async def generate_image(
    req: ImageGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskResponse:
    await _assert_reference_access(db, user, req)
    task = await create_media_task(
        db, user_id=user.id, task_type="image", model=req.model, params=req
    )
    return TaskResponse.model_validate(task)
