from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.security.auth import get_current_user, require_role
from app.security.ownership import is_admin

router = APIRouter()


@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    req: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
) -> User:
    """管理员创建用户（注册由管理端发起，不开放匿名注册）。"""
    username = req.username.strip()
    email = req.email.strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(req.password),
        role=req.role if req.role in ("admin", "user") else "user",
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户名或邮箱已被占用") from None
    await db.refresh(user)
    return user


@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db), _: User = Depends(require_role("admin"))
) -> list[User]:
    result = await db.execute(select(User))
    return list(result.scalars().all())


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> User:
    # 仅管理员或本人
    if not is_admin(current) and current.id != user_id:
        raise HTTPException(status_code=404, detail="用户不存在")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    req: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> User:
    # 管理员可改任何人；普通用户仅可改自己的非角色敏感字段
    if not is_admin(current) and current.id != user_id:
        raise HTTPException(status_code=404, detail="用户不存在")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if req.username is not None:
        user.username = req.username
    if req.email is not None:
        user.email = req.email
    if req.password is not None:
        user.password_hash = hash_password(req.password)
    if req.is_active is not None:
        if not is_admin(current):
            raise HTTPException(status_code=403, detail="无权修改账户状态")
        user.is_active = req.is_active

    try:
        await db.commit()
    except IntegrityError:
        # username/email 唯一约束冲突：预检后仍可能撞车，返回 409 而不是 500
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户名或邮箱已被占用") from None
    await db.refresh(user)
    return user
