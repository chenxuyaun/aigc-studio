from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import get_db
from app.models.prompt import Prompt
from app.models.prompt_category import PromptCategory
from app.models.prompt_favorite import PromptFavorite
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.prompt import PromptCreate, PromptResponse, PromptUpdate
from app.security.auth import get_current_user


def _prompt_hash(title: str, content: str) -> str:
    """去重 hash：与存量回填规则一致（sha256(title + \n + content)）。"""
    import hashlib

    return hashlib.sha256(f"{title}\n{content}".encode()).hexdigest()


router = APIRouter()


def _visibility_filter(user: User) -> ColumnElement[bool] | None:
    """私有内容可见性：公开 或 本人 或 管理员（admin 不过滤）。"""
    if user.role == "admin":
        return None
    return or_(Prompt.is_public.is_(True), Prompt.author_id == user.id)


def _can_view(p: Prompt, user: User) -> bool:
    if p.is_public:
        return True
    return p.author_id == user.id or user.role == "admin"


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    result = await db.execute(select(PromptCategory).order_by(PromptCategory.sort_order))
    cats = result.scalars().all()
    return {"items": [{"id": c.id, "name": c.name} for c in cats]}


@router.get("/mine/favorite-ids")
async def my_favorite_ids(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, list[str]]:
    rows = await db.execute(
        select(PromptFavorite.prompt_id).where(PromptFavorite.user_id == user.id)
    )
    return {"ids": [r for (r,) in rows.all()]}


@router.get("/mine/favorites", response_model=PaginatedResponse[PromptResponse])
async def my_favorites(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[PromptResponse]:
    base = (
        select(Prompt)
        .options(selectinload(Prompt.tags))
        .join(PromptFavorite, PromptFavorite.prompt_id == Prompt.id)
        .where(PromptFavorite.user_id == user.id)
    )
    vis = _visibility_filter(user)
    if vis is not None:
        base = base.where(vis)
    total = (
        await db.execute(
            select(func.count())
            .select_from(PromptFavorite)
            .where(PromptFavorite.user_id == user.id)
        )
    ).scalar() or 0
    result = await db.execute(
        base.order_by(PromptFavorite.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()
    return PaginatedResponse(
        items=[PromptResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/", response_model=PaginatedResponse[PromptResponse])
async def list_prompts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    prompt_type: str = Query(""),
    category_id: str = Query(""),
    tag: str = Query(""),
    sort: str = Query("latest"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[PromptResponse]:
    from app.models.prompt_tag import PromptTag
    from app.models.prompt_tag_relation import PromptTagRelation

    query = select(Prompt).options(selectinload(Prompt.tags))
    count_query = select(func.count(Prompt.id))
    vis = _visibility_filter(user)
    if vis is not None:
        query = query.where(vis)
        count_query = count_query.where(vis)
    if search:
        query = query.where(Prompt.title.contains(search))
        count_query = count_query.where(Prompt.title.contains(search))
    if prompt_type:
        query = query.where(Prompt.prompt_type == prompt_type)
        count_query = count_query.where(Prompt.prompt_type == prompt_type)
    if category_id:
        query = query.where(Prompt.category_id == category_id)
        count_query = count_query.where(Prompt.category_id == category_id)
    if tag:
        query = (
            query.join(PromptTagRelation, PromptTagRelation.prompt_id == Prompt.id)
            .join(PromptTag, PromptTag.id == PromptTagRelation.tag_id)
            .where(PromptTag.name == tag)
        )
        count_query = (
            count_query.join(PromptTagRelation, PromptTagRelation.prompt_id == Prompt.id)
            .join(PromptTag, PromptTag.id == PromptTagRelation.tag_id)
            .where(PromptTag.name == tag)
        )
    order = Prompt.use_count.desc() if sort == "popular" else Prompt.created_at.desc()
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.order_by(order).offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()
    return PaginatedResponse(
        items=[PromptResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


async def _set_prompt_tags(db: AsyncSession, prompt: Prompt, tags: list[str] | None) -> None:
    """按名称 upsert 标签并重建 prompt 的标签关系（空列表清空）。

    bulk 删除/插入关系行；调用方在 commit 后 expire 集合再重新查询，
    保证返回的 tags 与库一致（ORM 集合在 async 下避免隐式懒加载）。
    """
    from app.models.prompt_tag import PromptTag
    from app.models.prompt_tag_relation import PromptTagRelation

    names = [t.strip()[:50] for t in (tags or []) if t and t.strip()]
    await db.execute(sa_delete(PromptTagRelation).where(PromptTagRelation.prompt_id == prompt.id))
    for name in dict.fromkeys(names):  # 去重保序
        tag = (
            await db.execute(select(PromptTag).where(PromptTag.name == name))
        ).scalar_one_or_none()
        if tag is None:
            tag = PromptTag(name=name)
            db.add(tag)
            await db.flush()
        db.add(PromptTagRelation(prompt_id=prompt.id, tag_id=tag.id))


@router.get("/tags", response_model=list[dict[str, object]])
async def list_prompt_tags(db: AsyncSession = Depends(get_db)) -> list[dict[str, object]]:
    """全部标签 + 使用计数（供筛选 chips 展示）。"""
    from sqlalchemy import func as sa_func

    from app.models.prompt_tag import PromptTag
    from app.models.prompt_tag_relation import PromptTagRelation

    rows = (
        await db.execute(
            select(PromptTag.name, sa_func.count(PromptTagRelation.prompt_id))
            .outerjoin(PromptTagRelation, PromptTagRelation.tag_id == PromptTag.id)
            .group_by(PromptTag.id)
            .order_by(sa_func.count(PromptTagRelation.prompt_id).desc(), PromptTag.name)
        )
    ).all()
    return [{"name": name, "count": count} for name, count in rows]


@router.post("/", response_model=PromptResponse)
async def create_prompt(
    req: PromptCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> Prompt:
    prompt = Prompt(
        title=req.title,
        content=req.content,
        category_id=req.category_id,
        prompt_type=req.prompt_type,
        is_public=req.is_public,
        author_id=user.id,
        content_hash=_prompt_hash(req.title, req.content),
    )
    db.add(prompt)
    await db.flush()
    await _set_prompt_tags(db, prompt, req.tags)
    await db.commit()
    # 重新查询（带 tags）：expire 后强制重新加载，避免 identity map 返回旧集合
    db.expire(prompt, ["tags"])
    return (
        await db.execute(
            select(Prompt).options(selectinload(Prompt.tags)).where(Prompt.id == prompt.id)
        )
    ).scalar_one()


@router.get("/shared/{prompt_id}", response_model=PromptResponse)
async def get_shared_prompt(prompt_id: str, db: AsyncSession = Depends(get_db)) -> Prompt:
    """公开分享：无需登录，仅公开提示词可读（私有项一律 404，不泄露存在性）。"""
    result = await db.execute(
        select(Prompt).options(selectinload(Prompt.tags)).where(Prompt.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt or not prompt.is_public:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return prompt


@router.get("/{prompt_id}", response_model=PromptResponse)
async def get_prompt(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Prompt:
    result = await db.execute(
        select(Prompt).options(selectinload(Prompt.tags)).where(Prompt.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="提示词不存在")
    if not _can_view(prompt, user):
        raise HTTPException(status_code=404, detail="提示词不存在")
    return prompt


@router.put("/{prompt_id}", response_model=PromptResponse)
async def update_prompt(
    prompt_id: str,
    req: PromptUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Prompt:
    result = await db.execute(
        select(Prompt).options(selectinload(Prompt.tags)).where(Prompt.id == prompt_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="提示词不存在")
    if prompt.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权修改")
    data = req.model_dump(exclude_unset=True)
    tags = data.pop("tags", None)
    for field, value in data.items():
        setattr(prompt, field, value)
    # 标题/内容变更后重算去重 hash
    prompt.content_hash = _prompt_hash(prompt.title, prompt.content)
    if tags is not None:
        await _set_prompt_tags(db, prompt, tags)
    await db.commit()
    db.expire(prompt, ["tags"])
    return (
        await db.execute(
            select(Prompt).options(selectinload(Prompt.tags)).where(Prompt.id == prompt_id)
        )
    ).scalar_one()


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    result = await db.execute(select(Prompt).where(Prompt.id == prompt_id))
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="提示词不存在")
    if prompt.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权删除")
    await db.delete(prompt)
    await db.commit()
    return {"success": True, "data": None}


@router.post("/{prompt_id}/favorite")
async def toggle_favorite(
    prompt_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    prompt = (await db.execute(select(Prompt).where(Prompt.id == prompt_id))).scalar_one_or_none()
    if not prompt:
        raise HTTPException(status_code=404, detail="提示词不存在")
    existing = (
        await db.execute(
            select(PromptFavorite).where(
                PromptFavorite.user_id == user.id, PromptFavorite.prompt_id == prompt_id
            )
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        favorited = False
    else:
        db.add(PromptFavorite(user_id=user.id, prompt_id=prompt_id))
        favorited = True
    # 原子自增/自减：避免并发读-改-写丢计数（MySQL 下尤为重要）
    from sqlalchemy import update as sa_update

    await db.execute(
        sa_update(Prompt)
        .where(Prompt.id == prompt_id)
        .values(favorite_count=Prompt.favorite_count + (1 if favorited else -1))
    )
    await db.execute(
        sa_update(Prompt)
        .where(Prompt.id == prompt_id, Prompt.favorite_count < 0)
        .values(favorite_count=0)
    )
    await db.commit()
    await db.refresh(prompt)
    return {"favorited": favorited, "favorite_count": prompt.favorite_count}
