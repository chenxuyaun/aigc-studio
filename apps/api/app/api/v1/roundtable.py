"""通用创作圆桌 API：任意内容创作领域（文案/提示词/角色卡/图片/视频/漫画）多角色真讨论。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.security.auth import get_current_user
from app.services import roundtable_service

router = APIRouter()


class RoundtableRequest(BaseModel):
    # copy/prompt/character_card/image/video/comic
    domain: str = Field(default="copy", max_length=30)
    theme: str = Field(max_length=500)
    extra: str = Field(default="", max_length=2000)  # 领域附加信息（如风格要求）
    quick: bool = False
    use_web: bool = False  # 知识库命中不足时联网搜索兜底（新鲜题材）
    model: str = ""


@router.get("/domains")
async def roundtable_domains(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """可用创作领域列表。"""
    return {
        "domains": [{"id": k, "label": v["label"]} for k, v in roundtable_service._DOMAINS.items()]
    }


@router.post("/stream")
async def roundtable_stream(
    req: RoundtableRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """通用创作圆桌（SSE）：定制阵容 → 逐轮真讨论 → 主编把关定稿。"""

    async def _gen() -> AsyncIterator[str]:
        async for line in roundtable_service.stream_roundtable(
            db,
            user_id=user.id,
            domain=req.domain,
            theme=req.theme,
            extra=req.extra,
            quick=req.quick,
            use_web=req.use_web,
        ):
            yield line

    return StreamingResponse(_gen(), media_type="text/event-stream")
