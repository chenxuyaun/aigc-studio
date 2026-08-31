"""Core Runtime - Task 生命周期（创建 + 调度）。

从 services/generation_service.py 抽离：
- create_media_task: 落库 + 派发到后台处理
- _dispatch: 进程内或 Celery 调度选择

P0 边界：路由层（api/v1/generations/*）通过此模块创建 Task，不再直接 import
services.generation_service（后者在 P 阶段成为 Application 调度层）。
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.runtime.scheduler import schedule_media_task
from app.models.generation_task import GenerationTask

logger = logging.getLogger(__name__)


# 任务类型 → Celery 任务名（仅当 USE_CELERY_WORKER=1 时用）
_CELERY_TASK_BY_TYPE: dict[str, str] = {
    "text": "generate_text",
    "image": "generate_image",
    "video": "generate_video",
    "audio": "generate_audio",
    "music": "generate_audio",
}


def _dispatch(task_id: str, task_type: str) -> None:
    """默认进程内调度；USE_CELERY_WORKER=1 时投递队列。"""
    if int(getattr(settings, "USE_CELERY_WORKER", 0) or 0) == 1:
        from app.tasks.celery_app import celery_app

        name = _CELERY_TASK_BY_TYPE.get(task_type, "generate_image")
        celery_app.send_task(name, args=[task_id])
        return
    schedule_media_task(task_id)


async def create_media_task(
    db: AsyncSession,
    *,
    user_id: str,
    task_type: str,
    model: str,
    params: BaseModel,
    project_id: str | None = None,
) -> GenerationTask:
    """创建一个媒体生成任务并调度后台处理。

    路由层只做请求解析；任务落库与异步调度集中在此，便于后续切换到 Celery。
    """
    task = GenerationTask(
        task_type=task_type,
        status="queued",
        model=model,
        params=json.dumps(params.model_dump()),
        user_id=user_id,
        project_id=project_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    _dispatch(task.id, task_type)
    return task
