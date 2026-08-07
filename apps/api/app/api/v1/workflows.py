import json
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import get_db
from app.models.user import User
from app.models.workflow import Workflow
from app.models.workflow_category import WorkflowCategory
from app.models.workflow_favorite import WorkflowFavorite
from app.schemas.common import PaginatedResponse
from app.schemas.workflow import WorkflowCreate, WorkflowResponse, WorkflowUpdate
from app.security.auth import get_current_user
from app.services.call_logger import log_call
from app.services.provider_resolver import resolve_text_provider

router = APIRouter()


def _visibility_filter(user: User) -> ColumnElement[bool] | None:
    """私有内容可见性：公开 或 本人 或 管理员（admin 不过滤）。"""
    if user.role == "admin":
        return None
    return or_(Workflow.is_public.is_(True), Workflow.author_id == user.id)


def _can_view(wf: Workflow, user: User) -> bool:
    if wf.is_public:
        return True
    return wf.author_id == user.id or user.role == "admin"


def _with_dict(w: Workflow) -> dict[str, object]:
    data: dict[str, object] = {c.name: getattr(w, c.name) for c in w.__table__.columns}
    try:
        data["graph"] = json.loads(str(data.get("graph") or "{}"))
    except (ValueError, TypeError):
        data["graph"] = {}
    return data


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    result = await db.execute(select(WorkflowCategory).order_by(WorkflowCategory.sort_order))
    cats = result.scalars().all()
    return {"items": [{"id": c.id, "name": c.name} for c in cats]}


@router.get("/mine/favorite-ids")
async def my_favorite_ids(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, list[str]]:
    rows = await db.execute(
        select(WorkflowFavorite.workflow_id).where(WorkflowFavorite.user_id == user.id)
    )
    return {"ids": [r for (r,) in rows.all()]}


@router.get("/mine/favorites", response_model=PaginatedResponse[WorkflowResponse])
async def my_favorites(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[WorkflowResponse]:
    base = (
        select(Workflow)
        .join(WorkflowFavorite, WorkflowFavorite.workflow_id == Workflow.id)
        .where(WorkflowFavorite.user_id == user.id)
    )
    vis = _visibility_filter(user)
    if vis is not None:
        base = base.where(vis)
    total = (
        await db.execute(
            select(func.count())
            .select_from(WorkflowFavorite)
            .where(WorkflowFavorite.user_id == user.id)
        )
    ).scalar() or 0
    result = await db.execute(
        base.order_by(WorkflowFavorite.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()
    return PaginatedResponse(
        items=[WorkflowResponse.model_validate(_with_dict(i)) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get("/", response_model=PaginatedResponse[WorkflowResponse])
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    workflow_type: str = Query(""),
    category_id: str = Query(""),
    sort: str = Query("latest"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[WorkflowResponse]:
    query = select(Workflow)
    count_query = select(func.count(Workflow.id))
    vis = _visibility_filter(user)
    if vis is not None:
        query = query.where(vis)
        count_query = count_query.where(vis)
    if search:
        query = query.where(Workflow.name.contains(search))
        count_query = count_query.where(Workflow.name.contains(search))
    if workflow_type:
        query = query.where(Workflow.workflow_type == workflow_type)
        count_query = count_query.where(Workflow.workflow_type == workflow_type)
    if category_id:
        query = query.where(Workflow.category_id == category_id)
        count_query = count_query.where(Workflow.category_id == category_id)
    order = Workflow.use_count.desc() if sort == "popular" else Workflow.created_at.desc()
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.order_by(order).offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()
    return PaginatedResponse(
        items=[WorkflowResponse.model_validate(_with_dict(i)) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("/", response_model=WorkflowResponse)
async def create_workflow(
    req: WorkflowCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> WorkflowResponse:
    wf = Workflow(
        name=req.name,
        description=req.description,
        graph=json.dumps(req.graph, ensure_ascii=False),
        category_id=req.category_id,
        workflow_type=req.workflow_type,
        is_public=req.is_public,
        author_id=user.id,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return WorkflowResponse.model_validate(_with_dict(wf))


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowResponse:
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if not _can_view(wf, user):
        raise HTTPException(status_code=404, detail="工作流不存在")
    return WorkflowResponse.model_validate(_with_dict(wf))


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    req: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowResponse:
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if wf.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权修改")
    data = req.model_dump(exclude_unset=True)
    graph = data.pop("graph", None)
    for field, value in data.items():
        setattr(wf, field, value)
    if graph is not None:
        wf.graph = json.dumps(graph, ensure_ascii=False)
        wf.version += 1
    await db.commit()
    await db.refresh(wf)
    return WorkflowResponse.model_validate(_with_dict(wf))


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if wf.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权删除")
    await db.delete(wf)
    await db.commit()
    return {"success": True, "data": None}


@router.post("/{workflow_id}/duplicate", response_model=WorkflowResponse)
async def duplicate_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowResponse:
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if not _can_view(wf, user):
        raise HTTPException(status_code=404, detail="工作流不存在")
    import uuid as _uuid

    new_wf = Workflow(
        id=str(_uuid.uuid4()),
        name=f"{wf.name} (副本)",
        description=wf.description,
        graph=wf.graph,
        category_id=wf.category_id,
        workflow_type=wf.workflow_type,
        is_public=False,
        author_id=user.id,
        source_type="duplicate",
        cover_url=wf.cover_url,
        source_url=wf.source_url,
        source_author=wf.author_id,
        version=1,
    )
    db.add(new_wf)
    await db.commit()
    await db.refresh(new_wf)
    return WorkflowResponse.model_validate(_with_dict(new_wf))


@router.post("/{workflow_id}/favorite")
async def toggle_favorite(
    workflow_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    wf = (
        await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    ).scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")
    existing = (
        await db.execute(
            select(WorkflowFavorite).where(
                WorkflowFavorite.user_id == user.id,
                WorkflowFavorite.workflow_id == workflow_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        favorited = False
    else:
        db.add(WorkflowFavorite(user_id=user.id, workflow_id=workflow_id))
        favorited = True
    # 原子自增/自减：避免并发读-改-写丢计数（MySQL 下尤为重要）
    from sqlalchemy import update as sa_update

    await db.execute(
        sa_update(Workflow)
        .where(Workflow.id == workflow_id)
        .values(favorite_count=Workflow.favorite_count + (1 if favorited else -1))
    )
    await db.execute(
        sa_update(Workflow)
        .where(Workflow.id == workflow_id, Workflow.favorite_count < 0)
        .values(favorite_count=0)
    )
    await db.commit()
    await db.refresh(wf)
    return {"favorited": favorited, "favorite_count": wf.favorite_count}


def _topo_order(
    nodes: list[dict[str, object]], edges: list[dict[str, str]]
) -> list[dict[str, object]]:
    """Kahn 拓扑排序：上游先执行。存在环时抛 400。"""
    ids = [str(n.get("id")) for n in nodes]
    indeg = dict.fromkeys(ids, 0)
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        src, dst = str(e.get("source", "")), str(e.get("target", ""))
        if src in indeg and dst in indeg:
            adj[src].append(dst)
            indeg[dst] += 1
    queue = deque(i for i in ids if indeg[i] == 0)
    ordered: list[str] = []
    while queue:
        cur = queue.popleft()
        ordered.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if len(ordered) != len(ids):
        raise HTTPException(status_code=400, detail="工作流存在循环依赖，无法执行")
    by_id = {str(n.get("id")): n for n in nodes}
    return [by_id[i] for i in ordered]


def _node_prompt(node: dict[str, object], upstream: list[str]) -> str:
    """节点执行提示词：模板 + 上游输出。skill 节点用 params.prompt 或上游文本。"""
    data = node.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    node_type = str(node.get("type") or data.get("nodeType") or "")
    if node_type == "skill":
        params = data.get("params")
        params = params if isinstance(params, dict) else {}
        template = str(params.get("prompt") or "")
    else:
        template = str(data.get("promptContent") or data.get("systemPrompt") or "")
    parts = [p for p in (template.strip(), *[u.strip() for u in upstream]) if p]
    if not parts:
        parts = ["请根据你的能力生成一段有用的内容"]
    return "\n\n".join(parts)


async def _run_story_node(
    db: AsyncSession, user_id: str, node_type: str, params: dict[str, object],
    instruction: str, model: str,
) -> dict[str, object]:
    """Story Forge 创作节点：outline_gen（生成大纲）/ chapter_gen（生成章节）/ revise（修订）。"""
    from app.services import story_forge

    project_id = str(params.get("project_id") or "")
    if not project_id:
        return {"output": "（创作节点缺少 project_id 参数）", "error": "缺少 project_id"}
    if node_type == "outline_gen":
        chapters_raw = params.get("chapters")
        chapters = int(chapters_raw) if isinstance(chapters_raw, (int, str)) else 8
        result = await story_forge.generate_outline(
            db, user_id, project_id, chapters=chapters, model=model
        )
        if "error" in result:
            return {"output": f"（大纲生成失败：{result['error']}）", "error": result["error"]}
        names = "\n".join(
            f"- 第{c['chapter_no']}章《{c['title']}》：{c['outline']}" for c in result["chapters"]
        )
        return {"output": f"已生成 {len(result['chapters'])} 章大纲：\n{names}", "meta": result}
    if node_type == "revise":
        chapter_id = str(params.get("chapter_id") or "")
        if not chapter_id:
            return {"output": "（修订节点缺少 chapter_id 参数）", "error": "缺少 chapter_id"}
        result = await story_forge.revise_chapter(
            db, user_id, chapter_id, instruction, model=model
        )
        if "error" in result:
            return {"output": f"（修订失败：{result['error']}）", "error": result["error"]}
        return {"output": result["content"], "meta": result}
    # chapter_gen：取 chapter_no（缺省自动下一章）
    chapter_no = params.get("chapter_no")
    chapter = None
    if chapter_no is not None:
        target_no = int(chapter_no) if isinstance(chapter_no, (int, str)) else 0
        for c in await story_forge.list_chapters(db, user_id, project_id):
            if c["chapter_no"] == target_no:
                chapter = c
                break
    if chapter is None:
        created = await story_forge.create_chapter(db, user_id, project_id)
        chapter = story_forge._chapter_dict(created)
    result = await story_forge.generate_chapter(
        db, user_id, project_id, str(chapter["id"]), model=model, instruction=instruction
    )
    if "error" in result:
        return {"output": f"（章节生成失败：{result['error']}）", "error": result["error"]}
    return {"output": result["content"], "meta": result}


@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    """执行工作流：按拓扑序串联各节点（上游输出作为下游输入）逐一生成文本。

    每个节点一次 Provider 调用（失败回退 Mock），全部完成后返回各节点结果。
    """
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf or not _can_view(wf, user):
        raise HTTPException(status_code=404, detail="工作流不存在")
    try:
        graph = json.loads(wf.graph or "{}")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="工作流图数据损坏") from None
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    edges = graph.get("edges") if isinstance(graph, dict) else None
    if not isinstance(nodes, list) or not nodes:
        raise HTTPException(status_code=400, detail="工作流为空，请先在画布中添加节点")
    edges = edges if isinstance(edges, list) else []

    ordered = _topo_order(nodes, edges)
    results: dict[str, str] = {}
    story_results: dict[str, dict[str, object]] = {}
    for node in ordered:
        node_id = str(node.get("id"))
        upstream = [
            results[str(e.get("source"))]
            for e in edges
            if str(e.get("target")) == node_id and str(e.get("source")) in results
        ]
        prompt = _node_prompt(node, upstream)
        data = node.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        model = str(data.get("model") or "")
        # Story Forge 创作节点：走创作引擎（产出落库），不经过通用文本链路
        node_type = str(node.get("type") or data.get("nodeType") or "")
        if node_type in {"outline_gen", "chapter_gen", "revise"}:
            params = data.get("params")
            params = params if isinstance(params, dict) else {}
            sn = await _run_story_node(db, user.id, node_type, params, prompt, model)
            results[node_id] = str(sn.get("output") or "")
            story_results[node_id] = sn
            await log_call(
                task_type="story",
                provider="story_workflow",
                model=model,
                status="failed" if sn.get("error") else "succeeded",
                error_message=str(sn.get("error") or "")[:300],
                duration_ms=0,
                db=db,
            )
            continue
        resolved = await resolve_text_provider(db, model)
        error_note = ""
        started = time.monotonic()
        try:
            content = (await resolved.provider.generate(prompt, resolved.model)).content  # type: ignore[attr-defined]
        except Exception as exc:
            # 上游失败不降级假数据：节点输出错误说明
            error_note = f"{type(exc).__name__}: {str(exc)[:160]}"
            content = f"（生成失败：{error_note}）"
        await log_call(
            task_type="text",
            provider="workflow",
            model=model,
            status="failed" if error_note else "succeeded",
            error_message=error_note,
            duration_ms=int((time.monotonic() - started) * 1000),
            db=db,
        )
        results[node_id] = content

    wf.use_count += 1
    await db.commit()
    return {
        "success": True,
        "data": {
            "results": results,
            "story_results": story_results,
            "order": [str(n.get("id")) for n in ordered],
            "node_names": {
                str(n.get("id")): str((n.get("data") or {}).get("name") or "节点")
                for n in nodes
            },
        },
    }
