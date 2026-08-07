"""写真摄影真实数据种子：从 prompts 表下载真实 R2 CDN 图片，建立相册与照片。

- 按 source_author 分组，选 8 个高产作者各建一个相册（标题用真实主题）
- 每个相册下载 4-6 张真实图片到 storage/photography/{album_id}/{filename}
- 用 PIL 读真实 width/height/mime_type/size_bytes
- 幂等：按 album title 去重；photo 按 storage_key 去重
- 下载超时 10s/张，失败跳过不中断；总共 ~35 张

用法：
  python scripts/seed_photography.py
"""
from __future__ import annotations

import asyncio
import io
import sys
import uuid
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import httpx
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.photo import Photo
from app.models.photo_album import PhotoAlbum
from app.models.prompt import Prompt
from app.models.prompt_category import PromptCategory
from app.models.user import User
from PIL import Image
from sqlalchemy import func, select

STORAGE_ROOT = Path(settings.STORAGE_LOCAL_PATH)
DOWNLOAD_TIMEOUT = 10.0
NUM_AUTHORS = 8
PHOTOS_PER_ALBUM = 5

_FMT_TO_MIME = {
    "JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp",
    "GIF": "image/gif", "BMP": "image/bmp",
}

async def _admin_id(db) -> str:
    admin = (
        await db.execute(select(User).where(User.role == "admin").limit(1))
    ).scalar_one_or_none()
    if admin is None:
        raise RuntimeError("admin 用户不存在，请先初始化数据库")
    return admin.id


async def _pick_authors(db) -> list[tuple[str, str, str]]:
    """选 8 个高产作者，返回 (author, dominant_category_name, category_id)。"""
    rows = (
        await db.execute(
            select(Prompt.source_author, func.count(Prompt.id).label("cnt"))
            .where(Prompt.cover_url != "")
            .where(Prompt.source_author != "")
            .group_by(Prompt.source_author)
            .order_by(func.count(Prompt.id).desc())
            .limit(20)
        )
    ).all()
    cats = {c.name: c.id for c in (await db.execute(select(PromptCategory))).scalars().all()}
    selected: list[tuple[str, str, str]] = []
    for author, _cnt in rows:
        if len(selected) >= NUM_AUTHORS:
            break
        dom = (
            await db.execute(
                select(PromptCategory.name, func.count(Prompt.id).label("c"))
                .join(Prompt, Prompt.category_id == PromptCategory.id)
                .where(Prompt.source_author == author)
                .where(Prompt.cover_url != "")
                .group_by(PromptCategory.name)
                .order_by(func.count(Prompt.id).desc())
                .limit(1)
            )
        ).first()
        if dom is None:
            continue
        cat_name, cat_id = dom[0], cats.get(dom[0])
        if cat_id is None:
            continue
        selected.append((author, cat_name, cat_id))
    return selected


async def _author_prompts(db, author: str, limit: int) -> list[Prompt]:
    rows = (
        await db.execute(
            select(Prompt)
            .where(Prompt.source_author == author)
            .where(Prompt.cover_url != "")
            .order_by(Prompt.use_count.desc(), Prompt.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def _download_image(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        resp = await client.get(url, timeout=DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"  [跳过] 下载失败 {url[-40:]}: {e}")
        return None


def _image_meta(data: bytes) -> tuple[int, int, str] | None:
    try:
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        fmt = (img.format or "JPEG").upper()
        mime = _FMT_TO_MIME.get(fmt, "image/jpeg")
        return w, h, mime
    except Exception as e:
        print(f"  [跳过] PIL 解析失败: {e}")
        return None


async def main() -> None:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    async with AsyncSessionLocal() as db:
        admin_id = await _admin_id(db)
        authors = await _pick_authors(db)
        print(f"选定 {len(authors)} 个作者建相册: {[a[0] for a in authors]}")

        existing_albums = {
            a.title: a for a in (await db.execute(select(PhotoAlbum))).scalars().all()
        }
        total_photos = 0

        async with httpx.AsyncClient(follow_redirects=True) as client:
            for author, cat_name, _cat_id in authors:
                album_title = f"{author} · {cat_name}精选写真集"
                album = existing_albums.get(album_title)
                if album is None:
                    album = PhotoAlbum(
                        id=str(uuid.uuid4()),
                        title=album_title,
                        description=f"摄影师 {author} 的{cat_name}主题作品集，"
                                    "精选参考图，风格鲜明、构图考究，"
                                    "适合作为 AI 写真生成的灵感参考。",
                        style_tags=f"{cat_name},{author},写真,参考图",
                        is_public=True, photo_count=0, owner_id=admin_id,
                    )
                    db.add(album)
                    await db.flush()
                    existing_albums[album_title] = album
                    print(f"\n[新建相册] {album_title} (id={album.id})")
                else:
                    print(f"\n[已有相册] {album_title} (id={album.id})")

                existing_keys = {
                    p.storage_key for p in (
                        await db.execute(select(Photo).where(Photo.album_id == album.id))
                    ).scalars().all()
                }
                prompts = await _author_prompts(db, author, PHOTOS_PER_ALBUM + 3)
                album_dir = STORAGE_ROOT / "photography" / album.id
                album_dir.mkdir(parents=True, exist_ok=True)

                added = 0
                sort_idx = 0
                for p in prompts:
                    if added >= PHOTOS_PER_ALBUM:
                        break
                    fname = p.cover_url.rsplit("/", 1)[-1] or f"{p.id}.jpg"
                    storage_key = f"photography/{album.id}/{fname}"
                    if storage_key in existing_keys:
                        sort_idx += 1
                        continue
                    data = await _download_image(client, p.cover_url)
                    if data is None:
                        continue
                    meta = _image_meta(data)
                    if meta is None:
                        continue
                    w, h, mime = meta
                    (album_dir / fname).write_bytes(data)

                    photo = Photo(
                        id=str(uuid.uuid4()), album_id=album.id, filename=fname,
                        storage_key=storage_key, storage_backend="local",
                        mime_type=mime, size_bytes=len(data), width=w, height=h,
                        caption=p.title, sort_order=sort_idx, uploader_id=admin_id,
                    )
                    db.add(photo)
                    await db.flush()
                    existing_keys.add(storage_key)
                    added += 1
                    total_photos += 1
                    sort_idx += 1
                    print(f"  [下载] {fname}  {w}x{h}  {len(data)}B  {p.title[:30]}")
                    if album.cover_photo_id is None:
                        album.cover_photo_id = photo.id

                album.photo_count = (
                    await db.execute(
                        select(func.count(Photo.id)).where(Photo.album_id == album.id)
                    )
                ).scalar()
                await db.commit()

        print(f"\n完成：共下载 {total_photos} 张照片到 {len(authors)} 个相册")


if __name__ == "__main__":
    asyncio.run(main())

