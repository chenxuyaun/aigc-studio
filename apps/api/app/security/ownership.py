"""对象级鉴权与密钥轻度加密辅助。"""

from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi import HTTPException

from app.core.config import settings
from app.models.user import User


def clamp_page(page: int, page_size: int, *, max_size: int = 100) -> tuple[int, int]:
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 20)), max_size)
    return page, page_size


def is_admin(user: User) -> bool:
    return user.role == "admin"


def can_access_owner(user: User, owner_id: str | None) -> bool:
    if owner_id is None:
        return False
    return is_admin(user) or owner_id == user.id


def require_owned(user: User, owner_id: str | None, *, not_found: str = "资源不存在") -> None:
    """不存在与无权统一 404，避免枚举。"""
    if not can_access_owner(user, owner_id):
        raise HTTPException(status_code=404, detail=not_found)


def _fernet_key() -> bytes:
    # 由 APP_SECRET_KEY 派生 32 字节，避免额外依赖；非标准 Fernet，仅作模糊存储
    return hashlib.sha256(settings.APP_SECRET_KEY.encode("utf-8")).digest()


def seal_secret(plain: str) -> str:
    """可逆轻度封装（应用级密钥）。空串保持空。"""
    if not plain:
        return ""
    key = _fernet_key()
    raw = plain.encode("utf-8")
    # XOR stream from HMAC counter (simple, dependency-free)
    out = bytearray(len(raw))
    counter = 0
    pos = 0
    while pos < len(raw):
        block = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest()
        for b in block:
            if pos >= len(raw):
                break
            out[pos] = raw[pos] ^ b
            pos += 1
        counter += 1
    return "v1:" + base64.urlsafe_b64encode(bytes(out)).decode("ascii")


def open_secret(sealed: str) -> str:
    if not sealed:
        return ""
    if not sealed.startswith("v1:"):
        # 历史明文：读出但不在日志中使用
        return sealed
    raw = base64.urlsafe_b64decode(sealed[3:].encode("ascii"))
    key = _fernet_key()
    out = bytearray(len(raw))
    counter = 0
    pos = 0
    while pos < len(raw):
        block = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest()
        for b in block:
            if pos >= len(raw):
                break
            out[pos] = raw[pos] ^ b
            pos += 1
        counter += 1
    return bytes(out).decode("utf-8")


def secret_fingerprint(sealed_or_plain: str) -> str:
    """响应侧仅暴露是否已配置，不回传密钥。"""
    plain = open_secret(sealed_or_plain) if sealed_or_plain else ""
    if not plain:
        return ""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()[:8]
