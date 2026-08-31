"""Core Runtime - Asset 资源工具（URL / 下载 / MIME / 落库）。

从 services/task_runner.py 拆出：
- _download_media: 统一媒体下载（data URL + http，带 Grok UA 反盗链）
- _ext_from_mime: MIME → 文件扩展名
- _rewrite_media_url: 改写上游 URL 主机名（grok2api 返回 127.0.0.1 改写为容器内可访问 host）
- write_main_asset: 主资产落库 + 写终态（status=success/progress=100/result=json）
- write_object_and_record: 单 Asset 行（不含 comic panels/cover，那是 comic domain）

P0 边界：task_runner.py 通过 `from app.core.runtime.asset_writer import ...` 使用。
Comic panels/cover 落库留在 task_runner.py（P4 移到 applications/comic/）。
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.asset import Asset
from app.core.runtime.asset.access import sign_content_url
from app.storage import choose_write_backend, get_storage

logger = logging.getLogger(__name__)


async def _download_media(url: str) -> tuple[bytes, str]:
    """统一媒体下载：data URL 直接解码；http(s) URL 下载后按 content-type 定 MIME。

    grok 的 assets.grok.com 图片有防盗链（403）：必须带浏览器 UA + Referer，
    否则真实生图成功但下载失败（"图片下载 403"）。
    """
    if url.startswith("data:"):
        header, b64 = url.split(",", 1)
        mime = (
            header.split(":")[1].split(";")[0]
            if ":" in header
            else "application/octet-stream"
        )
        return base64.b64decode(b64), mime

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "Referer": "https://grok.com/",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"媒体下载 {resp.status_code}: {resp.text[:120]}")
    ctype = (resp.headers.get("content-type") or "application/octet-stream").lower()
    return resp.content, ctype


def _ext_from_mime(mime: str, default: str) -> str:
    mime = mime.lower()
    if "png" in mime:
        return "png"
    if "jpeg" in mime or "jpg" in mime:
        return "jpg"
    if "webp" in mime:
        return "webp"
    if "gif" in mime:
        return "gif"
    if "flac" in mime:
        return "flac"
    if "wav" in mime or "wave" in mime:
        return "wav"
    if "mp4" in mime:
        return "mp4"
    if "webm" in mime:
        return "webm"
    return default


def _rewrite_media_url(url: str, upstream_base: str) -> str:
    """上游返回的 media URL 常指向其容器内 127.0.0.1/localhost。

    按 provider base_url（如 http://host.docker.internal:8000/v1）的 host
    改写，保证 AIGC 容器内也能下载到 grok2api 的媒体。
    """
    if not url or not url.startswith(("http://", "https://")):
        return url
    try:
        u = urlparse(url)
        if u.hostname not in ("127.0.0.1", "localhost"):
            return url
        p = urlparse(upstream_base)
        if not p.hostname:
            return url
        return urlunparse(
            (p.scheme or u.scheme, p.netloc, u.path, u.params, u.query, u.fragment)
        )
    except ValueError:
        return url


async def write_main_asset_and_finalize(
    db: AsyncSession,
    *,
    task: Any,
    data: bytes,
    mime: str,
    ext: str,
    used_real: bool,
    model_name: str,
    fallback_reason: str,
    params: dict,
    comic_result: dict | None = None,
) -> Asset:
    """主资产落库 + 写终态（succeeded/progress=100/result=json）。

    comic panels/cover 子资产**不**在此函数处理（P4 移到 applications/comic/）。
    caller 拿到 Asset 对象后**自己**处理 comic 子资产。

    返回新创建的 Asset（**已 commit**）。
    """
    now = datetime.now(UTC)
    key = f"{task.user_id}/{now:%Y/%m}/{task.id}.{ext}"
    backend = choose_write_backend(task.user_id)
    store = get_storage(backend)
    await store.put(key, data, mime)

    asset = Asset(
        filename=f"{task.task_type}-{task.id[:8]}.{ext}",
        storage_key=key,
        storage_backend=backend,
        mime_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        user_id=task.user_id,
        task_id=task.id,
    )
    db.add(asset)
    try:
        await db.flush()
        # 写终态前重读：取消请求可能刚到达，不允许把已取消任务覆盖为成功
        from app.core.runtime.task import is_cancelled

        if await is_cancelled(db, task.id):
            logger.info("media_task_cancelled, task_id=%s, stage=%s", task.id, "before_terminal")
            await db.rollback()
            try:
                await store.delete(key)
            except Exception:
                logger.warning("cancelled_object_cleanup_failed, task_id=%s", task.id)
            raise _CancelledBeforeFinalize()
        task.status = "succeeded"
        task.progress = 100
        task.result = json.dumps(
            {
                "asset_id": asset.id,
                "url": sign_content_url(str(asset.id)),
                "access_url_endpoint": f"/api/v1/assets/{asset.id}/access-url",
                "mime": mime,
                "is_real": used_real,
                "provider": model_name if used_real else "mock",
                "fallback_reason": fallback_reason or None,
                "reference_photo_id": params.get("reference_photo_id"),
                "reference_asset_id": params.get("reference_asset_id"),
                "comic": (
                    {
                        "panels": [],
                        "assets": [],
                        "storyboard": "",
                        "title": "",
                        "cover": None,
                    }
                    if task.task_type == "comic"
                    else None
                ),
            }
        )
        task.completed_at = now
        await db.commit()
    except _CancelledBeforeFinalize:
        raise
    except Exception:
        # 写库失败：补偿删除对象，避免孤儿
        try:
            await store.delete(key)
        except Exception:
            logger.exception(
                "orphan_object_cleanup_failed, storage_backend=%s, storage_key=%s, task_id=%s",
                backend,
                key,
                task.id,
            )
        raise
    logger.info(
        "media_task_succeeded, task_id=%s, asset_id=%s, storage_backend=%s",
        task.id,
        asset.id,
        backend,
    )
    return asset


class _CancelledBeforeFinalize(Exception):
    """内部信号：任务在写终态前被取消。"""
