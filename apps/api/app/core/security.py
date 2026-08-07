from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from argon2 import PasswordHasher
from jose import jwt

ALGORITHM = "HS256"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    # verify() 抛 VerifyMismatchError（密码不符）或其他异常（哈希损坏）时均视为失败。
    try:
        return _hasher.verify(hashed, plain)
    except Exception:
        return False


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return str(jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=ALGORITHM))


def create_refresh_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(days=settings.JWT_REFRESH_TOKEN_DAYS))
    # jti 保证每个刷新令牌唯一（同秒多次登录也不会碰撞 token_hash）。
    to_encode.update({"exp": expire, "type": "refresh", "jti": secrets.token_hex(16)})
    return str(jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=ALGORITHM))


def verify_token(token: str) -> dict[str, Any] | None:
    try:
        decoded = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return dict(decoded)
    except Exception:
        return None
