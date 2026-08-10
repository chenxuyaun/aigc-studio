import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.models.generation_task import GenerationTask
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.generation import TaskResponse
from app.security.auth import get_current_user
from app.security.ownership import clamp_page

router = APIRouter()

_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "expired"})


@router.get("/", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(""),
    task_type: str = Query(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PaginatedResponse[TaskResponse]:
    page, page_size = clamp_page(page, page_size)
    query = select(GenerationTask)
    count_query = select(func.count(GenerationTask.id))
    # 非管理员仅可见自己的任务。
    if user.role != "admin":
        query = query.where(GenerationTask.user_id == user.id)
        count_query = count_query.where(GenerationTask.user_id == user.id)
    if status:
        query = query.where(GenerationTask.status == status)
        count_query = count_query.where(GenerationTask.status == status)
    if task_type:
        query = query.where(GenerationTask.task_type == task_type)
        count_query = count_query.where(GenerationTask.task_type == task_type)
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(GenerationTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()
    return PaginatedResponse(
        items=[TaskResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if page_size else 0,
    )


async def _get_owned_task(task_id: str, db: AsyncSession, user: User) -> GenerationTask:
    result = await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task or (task.user_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> TaskResponse:
    task = await _get_owned_task(task_id, db, user)
    return TaskResponse.model_validate(task)


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    task = await _get_owned_task(task_id, db, user)
    if task.status in _TERMINAL:
        raise HTTPException(status_code=409, detail="任务已结束，无法取消")
    task.status = "cancelled"
    await db.commit()
    return {"success": True, "data": None}


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    """失败任务原地重试：重置状态重新入队（同参数同 provider；断点续跑外壳）。"""
    task = await _get_owned_task(task_id, db, user)
    if task.status != "failed":
        raise HTTPException(status_code=409, detail="仅失败任务可重试")
    task.status = "queued"
    task.progress = 0
    task.error_message = ""
    task.completed_at = None
    task.result = ""
    await db.commit()
    # 按类型重新入队（与创建时的分发一致：Celery 队列或进程内调度）
    try:
        from app.services.generation_service import _dispatch

        _dispatch(task.id, task.task_type)
    except Exception as exc:
        task.status = "failed"
        task.error_message = f"重试入队失败：{str(exc)[:120]}"
        await db.commit()
        raise HTTPException(status_code=400, detail=task.error_message)
    return {"success": True, "data": None}


@router.delete("/{task_id}")
async def delete_task(
    task_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, object]:
    """删除任务记录。进行中的任务先取消语义：直接删库（产物素材保留）。"""
    task = await _get_owned_task(task_id, db, user)
    await db.delete(task)
    await db.commit()
    return {"success": True, "data": None}


@router.get("/{task_id}/events")
async def task_events(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """任务进度 SSE：必须已登录且对任务有所有权。

    浏览器原生 EventSource 无法带 Authorization；前端应使用 fetch 流
    （apiClient.streamSse 同类）或继续轮询 GET /tasks/{id}。
    """
    # 预检所有权（连接建立前 404）
    await _get_owned_task(task_id, db, user)
    owner_id = user.id
    is_admin = user.role == "admin"

    async def event_stream() -> AsyncIterator[str]:
        for _ in range(120):
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(GenerationTask).where(GenerationTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task or (task.user_id != owner_id and not is_admin):
                    yield f"data: {json.dumps({'type': 'error', 'message': '任务不存在'})}\n\n"
                    return
                # 进度流不回传完整 result 文本/资产，避免 SSE 日志侧信道
                payload = {
                    "type": "progress",
                    "status": task.status,
                    "progress": task.progress,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if task.status in _TERMINAL:
                    yield f"data: {json.dumps({'type': 'done', 'status': task.status})}\n\n"
                    return
            await asyncio.sleep(3)
        yield f"data: {json.dumps({'type': 'timeout'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
