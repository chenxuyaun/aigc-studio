import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import get_db
from app.models.agent import Agent
from app.models.agent_category import AgentCategory
from app.models.agent_favorite import AgentFavorite
from app.models.user import User
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate
from app.schemas.common import PaginatedResponse
from app.security.auth import get_current_user

router = APIRouter()


def _visibility_filter(user: User) -> ColumnElement[bool] | None:
    """私有内容可见性：公开 或 本人 或 管理员（admin 不过滤）。"""
    if user.role == "admin":
        return None
    return or_(Agent.is_public.is_(True), Agent.author_id == user.id)


def _can_view(a: Agent, user: User) -> bool:
    if a.is_public:
        return True
    return a.author_id == user.id or user.role == "admin"


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    result = await db.execute(select(AgentCategory).order_by(AgentCategory.sort_order))
    cats = result.scalars().all()
    return {"items": [{"id": c.id, "name": c.name} for c in cats]}


@router.get("/mine/favorite-ids")
async def my_favorite_ids(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, list[str]]:
    rows = await db.execute(select(AgentFavorite.agent_id).where(AgentFavorite.user_id == user.id))
    return {"ids": [r for (r,) in rows.all()]}


@router.get("/mine/favorites", response_model=PaginatedResponse[AgentResponse])
async def my_favorites(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[AgentResponse]:
    base = (
        select(Agent)
        .join(AgentFavorite, AgentFavorite.agent_id == Agent.id)
        .where(AgentFavorite.user_id == user.id)
    )
    vis = _visibility_filter(user)
    if vis is not None:
        base = base.where(vis)
    total = (
        await db.execute(
            select(func.count()).select_from(AgentFavorite).where(AgentFavorite.user_id == user.id)
        )
    ).scalar() or 0
    result = await db.execute(
        base.order_by(AgentFavorite.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()
    return PaginatedResponse(
        items=[AgentResponse.model_validate(_with_list(i)) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/", response_model=PaginatedResponse[AgentResponse])
async def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    agent_type: str = Query(""),
    category_id: str = Query(""),
    sort: str = Query("latest"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[AgentResponse]:
    query = select(Agent)
    count_query = select(func.count(Agent.id))
    vis = _visibility_filter(user)
    if vis is not None:
        query = query.where(vis)
        count_query = count_query.where(vis)
    if search:
        query = query.where(Agent.name.contains(search))
        count_query = count_query.where(Agent.name.contains(search))
    if agent_type:
        query = query.where(Agent.agent_type == agent_type)
        count_query = count_query.where(Agent.agent_type == agent_type)
    if category_id:
        query = query.where(Agent.category_id == category_id)
        count_query = count_query.where(Agent.category_id == category_id)
    order = Agent.use_count.desc() if sort == "popular" else Agent.created_at.desc()
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.order_by(order).offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()
    return PaginatedResponse(
        items=[AgentResponse.model_validate(_with_list(i)) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("/", response_model=AgentResponse)
async def create_agent(
    req: AgentCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> AgentResponse:
    agent = Agent(
        name=req.name,
        description=req.description,
        system_prompt=req.system_prompt,
        category_id=req.category_id,
        agent_type=req.agent_type,
        is_public=req.is_public,
        author_id=user.id,
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        tools=json.dumps(req.tools or [], ensure_ascii=False),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(_with_list(agent))


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentResponse:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not _can_view(agent, user):
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return AgentResponse.model_validate(_with_list(agent))


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    req: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentResponse:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if agent.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权修改")
    data = req.model_dump(exclude_unset=True)
    tools = data.pop("tools", None)
    for field, value in data.items():
        setattr(agent, field, value)
    if tools is not None:
        agent.tools = json.dumps(tools, ensure_ascii=False)
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(_with_list(agent))


@router.post("/{agent_id}/promote", response_model=AgentResponse)
async def promote_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentResponse:
    """Mission 现场角色转正：临时 Agent（source_type=mission）→ 正式 Agent。"""
    agent = (
        (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if agent.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权修改")
    agent.source_type = "user"
    if agent.agent_type == "mission":
        agent.agent_type = "generic"
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(_with_list(agent))


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if agent.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权删除")
    await db.delete(agent)
    await db.commit()
    return {"success": True, "data": None}


@router.post("/{agent_id}/favorite")
async def toggle_favorite(
    agent_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    existing = (
        await db.execute(
            select(AgentFavorite).where(
                AgentFavorite.user_id == user.id, AgentFavorite.agent_id == agent_id
            )
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        favorited = False
    else:
        db.add(AgentFavorite(user_id=user.id, agent_id=agent_id))
        favorited = True
    # 原子自增/自减：避免并发读-改-写丢计数（MySQL 下尤为重要）
    from sqlalchemy import update as sa_update

    await db.execute(
        sa_update(Agent)
        .where(Agent.id == agent_id)
        .values(favorite_count=Agent.favorite_count + (1 if favorited else -1))
    )
    await db.execute(
        sa_update(Agent)
        .where(Agent.id == agent_id, Agent.favorite_count < 0)
        .values(favorite_count=0)
    )
    await db.commit()
    await db.refresh(agent)
    return {"favorited": favorited, "favorite_count": agent.favorite_count}


def _with_list(a: Agent) -> dict[str, object]:
    """把 tools JSON 字段解析为 list，便于 response_model 序列化。"""
    data: dict[str, object] = {c.name: getattr(a, c.name) for c in a.__table__.columns}
    try:
        data["tools"] = json.loads(str(data.get("tools") or "[]"))
    except ValueError, TypeError:
        data["tools"] = []
    return data
