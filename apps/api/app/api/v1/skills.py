import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import get_db
from app.models.skill import Skill
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.skill import SkillCreate, SkillResponse, SkillUpdate
from app.security.auth import get_current_user

router = APIRouter()


def _visibility_filter(user: User) -> ColumnElement[bool] | None:
    """私有内容可见性：公开 或 本人 或 管理员（admin 不过滤）。"""
    if user.role == "admin":
        return None
    return or_(Skill.is_public.is_(True), Skill.author_id == user.id)


def _can_view(s: Skill, user: User) -> bool:
    if s.is_public:
        return True
    return s.author_id == user.id or user.role == "admin"


def _with_dict(s: Skill) -> dict[str, object]:
    data: dict[str, object] = {c.name: getattr(s, c.name) for c in s.__table__.columns}
    try:
        data["inputs_schema"] = json.loads(str(data.get("inputs_schema") or "{}"))
    except ValueError, TypeError:
        data["inputs_schema"] = {}
    return data


@router.get("/", response_model=PaginatedResponse[SkillResponse])
async def list_skills(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    skill_type: str = Query(""),
    sort: str = Query("latest"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[SkillResponse]:
    query = select(Skill)
    count_query = select(func.count(Skill.id))
    vis = _visibility_filter(user)
    if vis is not None:
        query = query.where(vis)
        count_query = count_query.where(vis)
    if search:
        query = query.where(Skill.name.contains(search))
        count_query = count_query.where(Skill.name.contains(search))
    if skill_type:
        query = query.where(Skill.skill_type == skill_type)
        count_query = count_query.where(Skill.skill_type == skill_type)
    order = Skill.use_count.desc() if sort == "popular" else Skill.created_at.desc()
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.order_by(order).offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()
    return PaginatedResponse(
        items=[SkillResponse.model_validate(_with_dict(i)) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("/", response_model=SkillResponse)
async def create_skill(
    req: SkillCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> SkillResponse:
    skill = Skill(
        name=req.name,
        description=req.description,
        instructions=req.instructions,
        skill_type=req.skill_type,
        model=req.model,
        is_public=req.is_public,
        author_id=user.id,
        inputs_schema=json.dumps(req.inputs_schema or {}, ensure_ascii=False),
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return SkillResponse.model_validate(_with_dict(skill))


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SkillResponse:
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    if not _can_view(skill, user):
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return SkillResponse.model_validate(_with_dict(skill))


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    req: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SkillResponse:
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    if skill.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权修改")
    data = req.model_dump(exclude_unset=True)
    schema = data.pop("inputs_schema", None)
    for field, value in data.items():
        setattr(skill, field, value)
    if schema is not None:
        skill.inputs_schema = json.dumps(schema, ensure_ascii=False)
    await db.commit()
    await db.refresh(skill)
    return SkillResponse.model_validate(_with_dict(skill))


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    if skill.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权删除")
    await db.delete(skill)
    await db.commit()
    return {"success": True, "data": None}
