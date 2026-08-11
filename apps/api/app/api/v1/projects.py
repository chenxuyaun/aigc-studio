from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.security.auth import get_current_user
from app.security.ownership import clamp_page, is_admin, require_owned

router = APIRouter()


def _owner_filter(user: User) -> ColumnElement[bool] | None:
    if is_admin(user):
        return None
    return Project.owner_id == user.id


@router.get("/", response_model=PaginatedResponse[ProjectResponse])
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[ProjectResponse]:
    page, page_size = clamp_page(page, page_size)
    query = select(Project)
    count_query = select(func.count(Project.id))
    filt = _owner_filter(user)
    if filt is not None:
        query = query.where(filt)
        count_query = count_query.where(filt)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(Project.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = result.scalars().all()
    return PaginatedResponse(
        items=[ProjectResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if page_size else 0,
    )


@router.post("/", response_model=ProjectResponse)
async def create_project(
    req: ProjectCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> Project:
    project = Project(name=req.name, description=req.description, owner_id=user.id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _get_owned_project(project_id: str, db: AsyncSession, user: User) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_owned(user, project.owner_id, not_found="项目不存在")
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    return await _get_owned_project(project_id, db, user)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    req: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = await _get_owned_project(project_id, db, user)
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}")
async def delete_project(
    project_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    project = await _get_owned_project(project_id, db, user)
    await db.delete(project)
    await db.commit()
    return {"success": True, "data": None}
