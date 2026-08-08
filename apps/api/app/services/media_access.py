"""媒体访问 URL 签发：local 走鉴权 content；r2 走短时预签名。"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.storage import get_storage

logger = structlog.get_logger()


class MediaAccess(BaseModel):
    url: str
    expires_at: datetime


# 旧字段 url / 头像 / 生成结果等直接 <img> 渲染场景的签名有效期（无 JWT、能力型 URL）
# 安全收紧：默认 10min（原 4h 过长，URL 一旦外泄即成长时间通行证）
_CONTENT_SIG_TTL = int(os.environ.get("ASSET_SIGNED_TTL_SECONDS", "600"))


def sign_content_url(object_id: str) -> str:
    """为本地资产 content 端点签发短期 HMAC 签名 URL（无需 JWT 即可在 <img> 加载）。"""
    exp = int(time.time()) + _CONTENT_SIG_TTL
    sig = hmac.new(
        settings.APP_SECRET_KEY.encode(),
        f"{object_id}:{exp}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"/api/v1/assets/{object_id}/content?exp={exp}&sig={sig}"


def verify_content_signature(object_id: str, exp: int, sig: str) -> bool:
    """校验签名 URL 的时效与完整性（HMAC 常量时间比较）。"""
    if int(time.time()) > exp:
        return False
    expected = hmac.new(
        settings.APP_SECRET_KEY.encode(),
        f"{object_id}:{exp}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    return hmac.compare_digest(expected, sig)


async def issue_media_access(
    *,
    storage_backend: str,
    storage_key: str,
    content_path: str,
    object_id: str,
) -> MediaAccess:
    """鉴权已在路由完成。返回可被浏览器直接加载的 URL。"""
    ttl = max(30, int(getattr(settings, "STORAGE_SIGNED_GET_TTL_SECONDS", 300) or 300))
    backend = (storage_backend or "local").strip().lower()
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)

    if backend == "local":
        # 相对 API 路径；前端带 JWT 访问 /content
        return MediaAccess(url=content_path, expires_at=expires_at)

    try:
        store = get_storage(backend)
        url = await store.signed_get_url(storage_key, expires_seconds=ttl)
    except Exception:
        logger.exception(
            "media_sign_failed",
            object_id=object_id,
            storage_backend=backend,
            # 不记录 key 以外的敏感 query
        )
        raise HTTPException(status_code=503, detail="媒体存储暂时不可用") from None

    return MediaAccess(url=url, expires_at=expires_at)
