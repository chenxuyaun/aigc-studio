from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.generation import TaskResponse, VideoGenerationRequest
from app.security.auth import get_current_user
from app.services.generation_service import create_media_task

router = APIRouter()


@router.post("/generate", response_model=TaskResponse)
async def generate_video(
    req: VideoGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskResponse:
    task = await create_media_task(
        db, user_id=user.id, task_type="video", model=req.model, params=req
    )
    return TaskResponse.model_validate(task)
