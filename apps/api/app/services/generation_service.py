from __future__ import annotations

import json

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.generation_task import GenerationTask
from app.services.task_runner import schedule_media_task

_CELERY_TASK_BY_TYPE = {
    "text": "generate_text",
    "image": "generate_image",
    "video": "generate_video",
    "audio": "generate_audio",
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
