"""创作工作台 API：主题 → AI 选角 → 建组（AI 导演工作室）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.security.auth import get_current_user
from app.services import creation_service

router = APIRouter()


class CreationPlanRequest(BaseModel):
    theme: str = Field(max_length=500)


class CreationScriptRequest(BaseModel):
    theme: str = Field(max_length=500)
    plan: dict[str, Any] | None = None  # 可选：角色方案（大纲按阵容写）
    variants: int = Field(default=1, ge=1, le=3)  # 多版本对比（并行生成）


class CreationReviewRequest(BaseModel):
    theme: str = Field(max_length=500)
    plan: dict[str, Any] | None = None
    script: dict[str, Any] | None = None  # 被评审的剧本大纲


class CreationSetupRequest(BaseModel):
    theme: str = Field(max_length=500)
    plan: dict[str, Any] | None = None  # 可选：前端确认后的方案


class CreationPublishRequest(BaseModel):
    chat_id: str = Field(min_length=8, max_length=64)
    title: str | None = Field(default=None, max_length=200)  # 可选：作品名（默认取群名）


@router.post("/plan")
async def creation_plan(
    req: CreationPlanRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """主题 → 角色方案（AI 选角导演，先检索用户知识库资料再选角）。"""
    return await creation_service.plan_project(db, req.theme, user_id=user.id)


@router.post("/script")
async def creation_script(
    req: CreationScriptRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """剧本初稿：主题（+角色方案）→ 分幕大纲；variants>1 时返回多版对比。"""
    return await creation_service.script_project(
        db, theme=req.theme, plan=req.plan, variants=req.variants
    )


@router.post("/review")
async def creation_review(
    req: CreationReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """剧本评审：评分/亮点/弱点/改进建议。"""
    return await creation_service.review_project(
        db, theme=req.theme, plan=req.plan, script=req.script
    )


@router.post("/publish")
async def creation_publish(
    req: CreationPublishRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """群演存档：群演出 → 完整剧本 → 存入创作工作室（story 项目+首章）。"""
    result = await creation_service.publish_project(
        db, user_id=user.id, chat_id=req.chat_id, title=req.title
    )
    await db.commit()
    return result


@router.post("/setup")
async def creation_setup(
    req: CreationSetupRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """按方案创建角色卡 + 自动建群（角色入群）。"""
    result = await creation_service.setup_project(
        db, owner_id=user.id, theme=req.theme, plan=req.plan
    )
    await db.commit()
    return result
