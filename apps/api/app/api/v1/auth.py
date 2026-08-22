import contextlib
import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import check_rate_limit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
    verify_token,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse
from app.schemas.user import UserResponse
from app.security.auth import get_current_user

router = APIRouter()


async def _cleanup_expired_tokens(db: AsyncSession) -> None:
    """清理已过期/已撤销的刷新令牌行（每次登录/刷新顺带执行，避免表无限增长）。"""
    with contextlib.suppress(Exception):
        await db.execute(delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(UTC)))


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    check_rate_limit(
        request,
        limit=int(settings.RATE_LIMIT_LOGIN_PER_MINUTE or 20),
        bucket="login",
    )
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    # 用户不存在也执行一次假校验：抹平计时差异，防账号枚举
    if not user:
        verify_password(req.password, "$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")
    access_token = create_access_token({"sub": user.id, "role": user.role})
    refresh_token = create_refresh_token({"sub": user.id})
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_DAYS),
    )
    db.add(rt)
    await _cleanup_expired_tokens(db)
    await db.commit()
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    payload = verify_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="无效的刷新令牌")
    token_hash = hashlib.sha256(req.refresh_token.encode()).hexdigest()
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    rt = result.scalar_one_or_none()
    if not rt:
        raise HTTPException(status_code=401, detail="刷新令牌已撤销")
    # DB 过期列兜底：即使 JWT 未过期（时钟偏差等）也不放行。
    # SQLite 存 naive UTC（迁移用 CURRENT_TIMESTAMP），比较前统一补时区。
    if rt.expires_at is not None:
        expires = rt.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < datetime.now(UTC):
            raise HTTPException(status_code=401, detail="刷新令牌已过期")
    # refresh JWT 本身不含 role；从用户表取当前角色，避免 admin 刷新后降级为 user。
    user = (await db.execute(select(User).where(User.id == payload["sub"]))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")
    access_token = create_access_token({"sub": user.id, "role": user.role})
    new_refresh_token = create_refresh_token({"sub": user.id})
    new_hash = hashlib.sha256(new_refresh_token.encode()).hexdigest()
    rt.token_hash = new_hash
    rt.expires_at = datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_DAYS)
    await _cleanup_expired_tokens(db)
    await db.commit()
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    result = await db.execute(select(RefreshToken).where(RefreshToken.user_id == current_user.id))
    for rt in result.scalars().all():
        await db.delete(rt)
    await db.commit()
    return {"success": True, "data": None}


@router.post("/auto-login", response_model=TokenResponse)
async def auto_login(request: Request, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """个人服务器免登录入口：nginx 注入 X-Auto-Login-Key 头校验通过后，
    直接为 AUTO_LOGIN_USERNAME 签发 token（无需密码）。

    安全边界：
    - AUTO_LOGIN_KEY 为空 → 功能关闭（默认）
    - 密钥只存在于服务器 .env + nginx 配置，公网请求无法伪造该头
    - 仅信任 nginx 反代路径；直连容器端口（内网）也能用，但密钥仍不可见
    """
    if not settings.AUTO_LOGIN_KEY:
        raise HTTPException(status_code=404, detail="自动登录未启用")
    supplied = request.headers.get("x-auto-login-key", "")
    if not supplied or supplied != settings.AUTO_LOGIN_KEY:
        raise HTTPException(status_code=403, detail="自动登录密钥无效")
    if not settings.AUTO_LOGIN_USERNAME:
        raise HTTPException(status_code=403, detail="未配置自动登录账号")
    user = (
        await db.execute(select(User).where(User.username == settings.AUTO_LOGIN_USERNAME))
    ).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="自动登录账号不存在或已禁用")
    access_token = create_access_token({"sub": user.id, "role": user.role})
    refresh_token = create_refresh_token({"sub": user.id})
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_DAYS),
    )
    db.add(rt)
    await _cleanup_expired_tokens(db)
    await db.commit()
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
