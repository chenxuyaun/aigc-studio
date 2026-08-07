import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.asset import Asset
from app.models.user import User
from app.security.auth import get_current_user
from app.services.media_access import MediaAccess, issue_media_access
from app.storage import choose_write_backend, get_storage

router = APIRouter()

# 上传限制：单文件最大 20 MB
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_CHUNK = 1024 * 256

# 允许的素材类型：图片（魔数校验）+ 音频（WAV/FLAC/MP3 头校验）
_ALLOWED_PREFIXES = ("image/", "audio/", "video/")


def _sanitize_filename(name: str | None) -> str:
    """清洗文件名：去路径分隔符、控制字符，按 255 截断，避免 DataError 500。"""
    base = (name or "uploaded").replace("\\", "/").split("/")[-1].strip()
    base = "".join(ch for ch in base if ch >= " " and ch not in ('"', "'", "<", ">", "|"))
    base = base or "uploaded"
    return base[:255]


async def _read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """分块读取并限流，避免整文件先读入内存再判大小（超限即中断）。"""
    buf = bytearray()
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，最大允许 {max_bytes // 1024 // 1024} MB",
            )
    return bytes(buf)


def _inspect_upload(data: bytes, declared: str) -> str:
    """按魔数嗅探真实 MIME；与声明类型不一致或不可识别则 400。

    防存储型 XSS：客户端声明 text/html 也能被识破并拒绝。
    """
    mime = "application/octet-stream"
    if data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    elif data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        mime = "audio/wav"
    elif data.startswith(b"fLaC"):
        mime = "audio/flac"
    elif data.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3")):
        mime = "audio/mpeg"
    elif data.startswith((b"\x00\x00\x00", b"moov", b"ftyp")):
        mime = "video/mp4"
    elif data.startswith(b"\x1a\x45\xdf\xa3"):
        mime = "video/webm"

    if mime == "application/octet-stream":
        raise HTTPException(status_code=400, detail="无法识别的文件类型")
    if not mime.startswith(_ALLOWED_PREFIXES):
        raise HTTPException(status_code=400, detail=f"不支持的素材类型：{mime}")
    declared_lower = (declared or "").lower()
    # 声明类型不匹配且声明的是危险类型时拒绝（宽松匹配主/子类型）
    if declared_lower and mime.split("/")[0] != declared_lower.split("/")[0]:
        raise HTTPException(status_code=400, detail=f"文件内容与声明类型不符：{declared}")
    return mime


def _serialize(a: Asset) -> dict[str, object]:
    return {
        "id": a.id,
        "filename": a.filename,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "task_id": a.task_id,
        "storage_backend": getattr(a, "storage_backend", None) or "local",
        "created_at": a.created_at.isoformat() if a.created_at else None,
        # 兼容旧客户端：仍指向 content；新客户端优先 access_url_endpoint
        "url": f"/api/v1/assets/{a.id}/content",
        "access_url_endpoint": f"/api/v1/assets/{a.id}/access-url",
    }


@router.get("/")
async def list_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    mime_prefix: str = Query("", description="如 image/ 或 audio/"),
    task_id: str = Query(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    from app.security.ownership import clamp_page

    page, page_size = clamp_page(page, page_size)
    filters = [Asset.user_id == user.id]
    if mime_prefix.strip():
        filters.append(Asset.mime_type.startswith(mime_prefix.strip()))
    if task_id.strip():
        filters.append(Asset.task_id == task_id.strip())

    total = (await db.execute(select(func.count(Asset.id)).where(*filters))).scalar() or 0
    result = await db.execute(
        select(Asset)
        .where(*filters)
        .order_by(Asset.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()
    pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "items": [_serialize(a) for a in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


@router.post("/", response_model=dict)
async def upload_asset(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    """直接上传素材文件（图片 / 音频），存入存储并创建素材记录。"""
    # 分块限读 + 魔数嗅探，避免超大文件打爆内存与存储型 XSS
    data = await _read_upload_limited(file, MAX_UPLOAD_BYTES)

    # 按用户总配额限制（0=不限）
    quota = int(settings.USER_STORAGE_QUOTA_BYTES or 0)
    if quota > 0:
        used = (
            await db.execute(
                select(func.coalesce(func.sum(Asset.size_bytes), 0)).where(
                    Asset.user_id == user.id
                )
            )
        ).scalar() or 0
        if used + len(data) > quota:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"存储配额不足（已用 {used // 1024 // 1024}MB，"
                    f"上限 {quota // 1024 // 1024}MB）"
                ),
            )

    mime = _inspect_upload(data, file.content_type or "")

    now = datetime.now(UTC)
    safe_name = _sanitize_filename(file.filename)
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    # key 带唯一前缀：同内容同分钟重复上传不再共用存储 key（避免删一损二）
    unique = uuid.uuid4().hex[:8]
    key = f"{user.id}/upload/{now:%Y/%m}/{unique}-{hashlib.sha256(data).hexdigest()[:16]}.{ext}"

    backend = choose_write_backend(user.id)
    store = get_storage(backend)
    await store.put(key, data, mime)

    asset = Asset(
        filename=safe_name,
        storage_key=key,
        storage_backend=backend,
        mime_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        user_id=user.id,
        task_id=None,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return _serialize(asset)


@router.get("/{asset_id}")
async def get_asset(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    asset = await _get_owned_asset(asset_id, db, user)
    return _serialize(asset)


async def _get_owned_asset(asset_id: str, db: AsyncSession, user: User) -> Asset:
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    # 对象级鉴权：非管理员只能访问自己的素材（不存在与无权同样返回 404，避免枚举）。
    if not asset or (asset.user_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="素材不存在")
    return asset


@router.get("/{asset_id}/access-url", response_model=MediaAccess)
async def get_asset_access_url(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MediaAccess:
    asset = await _get_owned_asset(asset_id, db, user)
    backend = getattr(asset, "storage_backend", None) or "local"
    content_path = f"/api/v1/assets/{asset.id}/content"
    return await issue_media_access(
        storage_backend=backend,
        storage_key=asset.storage_key,
        content_path=content_path,
        object_id=asset.id,
    )


@router.get("/{asset_id}/content")
async def get_asset_content(
    asset_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    asset = await _get_owned_asset(asset_id, db, user)
    backend = getattr(asset, "storage_backend", None) or "local"
    if backend != "local":
        # R2：307 到短时预签名，避免 API 中转大文件
        access = await issue_media_access(
            storage_backend=backend,
            storage_key=asset.storage_key,
            content_path=f"/api/v1/assets/{asset.id}/content",
            object_id=asset.id,
        )
        return Response(
            status_code=307,
            headers={
                "Location": access.url,
                "Cache-Control": "private, no-store",
            },
        )
    data = await get_storage("local").get(asset.storage_key)
    return Response(
        content=data,
        media_type=asset.mime_type,
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    asset = await _get_owned_asset(asset_id, db, user)
    backend = getattr(asset, "storage_backend", None) or "local"
    ok = await get_storage(backend).delete(asset.storage_key)
    if not ok:
        # 不删库，便于重试清理孤儿/假删除
        raise HTTPException(status_code=503, detail="存储删除失败，请稍后重试")
    await db.delete(asset)
    await db.commit()
    return {"success": True, "data": None}
