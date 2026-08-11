"""写真摄影：相册与照片上传/浏览 API。"""

from __future__ import annotations

import contextlib
import io
import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.photo import Photo
from app.models.photo_album import PhotoAlbum
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.photography import (
    AlbumCreate,
    AlbumResponse,
    AlbumUpdate,
    PhotoResponse,
    PhotoUpdate,
)
from app.security.auth import get_current_user
from app.services.media_access import MediaAccess, issue_media_access
from app.storage import choose_write_backend, get_storage

router = APIRouter()

ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/jpg",
}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB per file
MAX_BATCH_BYTES = 100 * 1024 * 1024  # 100MB per request
CHUNK = 1024 * 1024


def _album_response(album: PhotoAlbum) -> AlbumResponse:
    cover_url = (
        f"/api/v1/photography/photos/{album.cover_photo_id}/content"
        if album.cover_photo_id
        else None
    )
    cover_access = (
        f"/api/v1/photography/photos/{album.cover_photo_id}/access-url"
        if album.cover_photo_id
        else None
    )
    return AlbumResponse(
        id=album.id,
        title=album.title,
        description=album.description,
        cover_photo_id=album.cover_photo_id,
        cover_url=cover_url,
        cover_access_url_endpoint=cover_access,
        style_tags=album.style_tags,
        is_public=album.is_public,
        photo_count=album.photo_count,
        owner_id=album.owner_id,
        created_at=album.created_at,
        updated_at=album.updated_at,
    )


def _photo_response(photo: Photo) -> PhotoResponse:
    return PhotoResponse(
        id=photo.id,
        album_id=photo.album_id,
        filename=photo.filename,
        mime_type=photo.mime_type,
        size_bytes=photo.size_bytes,
        width=photo.width,
        height=photo.height,
        caption=photo.caption,
        sort_order=photo.sort_order,
        storage_backend=getattr(photo, "storage_backend", None) or "local",
        url=f"/api/v1/photography/photos/{photo.id}/content",
        access_url_endpoint=f"/api/v1/photography/photos/{photo.id}/access-url",
        created_at=photo.created_at,
    )


async def _read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    buf = bytearray()
    while True:
        chunk = await upload.read(CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"文件过大（>{max_bytes // (1024 * 1024)}MB）",
            )
    return bytes(buf)


def _inspect_image(data: bytes) -> tuple[str, int, int]:
    """返回 (mime, width, height)；损坏图片抛 400。"""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            width, height = img.size
            fmt = (img.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise HTTPException(status_code=400, detail="无法识别的图片文件") from exc
    mime = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "GIF": "image/gif",
    }.get(fmt)
    if not mime:
        raise HTTPException(status_code=400, detail=f"不支持的图片格式：{fmt or 'unknown'}")
    return mime, int(width or 0), int(height or 0)


async def _get_album_or_404(album_id: str, db: AsyncSession) -> PhotoAlbum:
    album = (
        await db.execute(select(PhotoAlbum).where(PhotoAlbum.id == album_id))
    ).scalar_one_or_none()
    if not album:
        raise HTTPException(status_code=404, detail="相册不存在")
    return album


def _can_view(album: PhotoAlbum, user: User | None) -> bool:
    if album.is_public:
        return True
    if user is None:
        return False
    return album.owner_id == user.id or user.role == "admin"


def _can_edit(album: PhotoAlbum, user: User) -> bool:
    return album.owner_id == user.id or user.role == "admin"


@router.get("/albums", response_model=PaginatedResponse[AlbumResponse])
async def list_albums(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    search: str = Query(""),
    mine: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[AlbumResponse]:
    query = select(PhotoAlbum)
    count_query = select(func.count(PhotoAlbum.id))

    if mine:
        query = query.where(PhotoAlbum.owner_id == user.id)
        count_query = count_query.where(PhotoAlbum.owner_id == user.id)
    else:
        visible = or_(PhotoAlbum.is_public.is_(True), PhotoAlbum.owner_id == user.id)
        if user.role != "admin":
            query = query.where(visible)
            count_query = count_query.where(visible)

    if search.strip():
        like = f"%{search.strip()}%"
        filt = or_(PhotoAlbum.title.like(like), PhotoAlbum.style_tags.like(like))
        query = query.where(filt)
        count_query = count_query.where(filt)

    total = (await db.execute(count_query)).scalar() or 0
    rows = (
        (
            await db.execute(
                query.order_by(PhotoAlbum.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    return PaginatedResponse(
        items=[_album_response(a) for a in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if page_size else 0,
    )


@router.post("/albums", response_model=AlbumResponse)
async def create_album(
    req: AlbumCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlbumResponse:
    album = PhotoAlbum(
        title=req.title.strip(),
        description=req.description.strip(),
        style_tags=req.style_tags.strip(),
        is_public=req.is_public,
        owner_id=user.id,
    )
    db.add(album)
    await db.commit()
    await db.refresh(album)
    return _album_response(album)


@router.get("/albums/{album_id}", response_model=AlbumResponse)
async def get_album(
    album_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlbumResponse:
    album = await _get_album_or_404(album_id, db)
    if not _can_view(album, user):
        raise HTTPException(status_code=404, detail="相册不存在")
    return _album_response(album)


@router.put("/albums/{album_id}", response_model=AlbumResponse)
async def update_album(
    album_id: str,
    req: AlbumUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlbumResponse:
    album = await _get_album_or_404(album_id, db)
    if not _can_edit(album, user):
        raise HTTPException(status_code=403, detail="无权修改此相册")

    data = req.model_dump(exclude_unset=True)
    if data.get("cover_photo_id"):
        photo = (
            await db.execute(
                select(Photo).where(Photo.id == data["cover_photo_id"], Photo.album_id == album.id)
            )
        ).scalar_one_or_none()
        if not photo:
            raise HTTPException(status_code=400, detail="封面照片不属于该相册")

    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(album, field, value)

    await db.commit()
    await db.refresh(album)
    return _album_response(album)


@router.delete("/albums/{album_id}")
async def delete_album(
    album_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    album = await _get_album_or_404(album_id, db)
    if not _can_edit(album, user):
        raise HTTPException(status_code=403, detail="无权删除此相册")

    photos = (await db.execute(select(Photo).where(Photo.album_id == album.id))).scalars().all()
    for photo in photos:
        backend = getattr(photo, "storage_backend", None) or "local"
        with contextlib.suppress(Exception):
            await get_storage(backend).delete(photo.storage_key)
        await db.delete(photo)

    await db.delete(album)
    await db.commit()
    return {"success": True, "data": None}


@router.get("/albums/{album_id}/photos", response_model=PaginatedResponse[PhotoResponse])
async def list_photos(
    album_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(48, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[PhotoResponse]:
    album = await _get_album_or_404(album_id, db)
    if not _can_view(album, user):
        raise HTTPException(status_code=404, detail="相册不存在")

    total = (
        await db.execute(select(func.count(Photo.id)).where(Photo.album_id == album.id))
    ).scalar() or 0
    rows = (
        (
            await db.execute(
                select(Photo)
                .where(Photo.album_id == album.id)
                .order_by(Photo.sort_order.asc(), Photo.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    return PaginatedResponse(
        items=[_photo_response(p) for p in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if page_size else 0,
    )


@router.post("/albums/{album_id}/photos", response_model=list[PhotoResponse])
async def upload_photos(
    album_id: str,
    files: list[UploadFile] = File(...),
    captions: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PhotoResponse]:
    """上传一张或多张照片到相册。captions 可为空，或用 `||` 分隔与 files 对齐。"""
    album = await _get_album_or_404(album_id, db)
    if not _can_edit(album, user):
        raise HTTPException(status_code=403, detail="无权上传到此相册")
    if not files:
        raise HTTPException(status_code=400, detail="请选择至少一张图片")
    if len(files) > 30:
        raise HTTPException(status_code=400, detail="单次最多上传 30 张")

    caption_list = [c.strip() for c in captions.split("||")] if captions else []
    backend = choose_write_backend(user.id)
    storage = get_storage(backend)
    created: list[Photo] = []
    written_keys: list[str] = []
    batch_bytes = 0

    max_sort = (
        await db.execute(select(func.max(Photo.sort_order)).where(Photo.album_id == album.id))
    ).scalar()
    next_sort = (max_sort or 0) + 1

    try:
        for idx, upload in enumerate(files):
            raw_name = upload.filename or f"photo-{idx + 1}.jpg"
            data = await _read_upload_limited(upload, MAX_UPLOAD_BYTES)
            if not data:
                raise HTTPException(status_code=400, detail=f"空文件：{raw_name}")
            batch_bytes += len(data)
            if batch_bytes > MAX_BATCH_BYTES:
                raise HTTPException(status_code=400, detail="单次上传总大小超过 100MB")

            mime, width, height = _inspect_image(data)
            photo_id = str(uuid.uuid4())
            ext = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/gif": ".gif",
            }.get(mime, PurePosixPath(raw_name).suffix.lower() or ".jpg")
            storage_key = f"photography/{album.id}/{photo_id}{ext}"
            await storage.put(storage_key, data, content_type=mime)
            written_keys.append(storage_key)

            caption = caption_list[idx] if idx < len(caption_list) else ""
            photo = Photo(
                id=photo_id,
                album_id=album.id,
                filename=raw_name[:255],
                storage_key=storage_key,
                storage_backend=backend,
                mime_type=mime,
                size_bytes=len(data),
                width=width,
                height=height,
                caption=caption,
                sort_order=next_sort + idx,
                uploader_id=user.id,
            )
            db.add(photo)
            created.append(photo)

        album.photo_count = (album.photo_count or 0) + len(created)
        if not album.cover_photo_id and created:
            album.cover_photo_id = created[0].id

        await db.commit()
    except Exception:
        for key in written_keys:
            with contextlib.suppress(Exception):
                await storage.delete(key)
        raise

    for p in created:
        await db.refresh(p)
    return [_photo_response(p) for p in created]


@router.get("/photos/{photo_id}/access-url", response_model=MediaAccess)
async def get_photo_access_url(
    photo_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MediaAccess:
    photo = (await db.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")
    album = await _get_album_or_404(photo.album_id, db)
    if not _can_view(album, user):
        raise HTTPException(status_code=404, detail="照片不存在")
    backend = getattr(photo, "storage_backend", None) or "local"
    return await issue_media_access(
        storage_backend=backend,
        storage_key=photo.storage_key,
        content_path=f"/api/v1/photography/photos/{photo.id}/content",
        object_id=photo.id,
    )


@router.get("/photos/{photo_id}/content")
async def get_photo_content(
    photo_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    photo = (await db.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")
    album = await _get_album_or_404(photo.album_id, db)
    if not _can_view(album, user):
        raise HTTPException(status_code=404, detail="照片不存在")
    backend = getattr(photo, "storage_backend", None) or "local"
    if backend != "local":
        access = await issue_media_access(
            storage_backend=backend,
            storage_key=photo.storage_key,
            content_path=f"/api/v1/photography/photos/{photo.id}/content",
            object_id=photo.id,
        )
        return Response(
            status_code=307,
            headers={"Location": access.url, "Cache-Control": "private, no-store"},
        )
    data = await get_storage("local").get(photo.storage_key)
    return Response(
        content=data,
        media_type=photo.mime_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.put("/photos/{photo_id}", response_model=PhotoResponse)
async def update_photo(
    photo_id: str,
    req: PhotoUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PhotoResponse:
    photo = (await db.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")
    album = await _get_album_or_404(photo.album_id, db)
    if not _can_edit(album, user):
        raise HTTPException(status_code=403, detail="无权修改此照片")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(photo, field, value)
    await db.commit()
    await db.refresh(photo)
    return _photo_response(photo)


@router.delete("/photos/{photo_id}")
async def delete_photo(
    photo_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    photo = (await db.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")
    album = await _get_album_or_404(photo.album_id, db)
    if not _can_edit(album, user):
        raise HTTPException(status_code=403, detail="无权删除此照片")

    backend = getattr(photo, "storage_backend", None) or "local"
    ok = await get_storage(backend).delete(photo.storage_key)
    if not ok:
        raise HTTPException(status_code=503, detail="存储删除失败，请稍后重试")

    if album.cover_photo_id == photo.id:
        album.cover_photo_id = None
    album.photo_count = max(0, (album.photo_count or 1) - 1)
    await db.delete(photo)
    await db.commit()

    if album.cover_photo_id is None and album.photo_count > 0:
        nxt = (
            await db.execute(
                select(Photo)
                .where(Photo.album_id == album.id)
                .order_by(Photo.sort_order.asc(), Photo.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if nxt:
            album.cover_photo_id = nxt.id
            await db.commit()

    return {"success": True, "data": None}
