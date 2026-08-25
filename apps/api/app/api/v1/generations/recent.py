"""最近的生成作品（首页作品预览数据源）。

拉取当前用户最近的成功媒体生成任务（image/audio/comic/music/video），
解析 result JSON 出 asset_url / cover_url 等可展示字段，供 AI 助手首页「最近作品」区预览。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.generation_task import GenerationTask
from app.models.user import User
from app.security.auth import get_current_user
from app.services.media_access import sign_content_url

router = APIRouter(tags=["generations"])

# 媒体类型；文本/提示词不展示在作品区
_MEDIA_TYPES = ("image", "audio", "comic", "music", "video")


def _asset_fresh_url(value: Any) -> str | None:
    """从 result 里的一个资产字段值解析可展示的即时有效 URL。

    value 可能是：
      - dict：含 asset_id（优先实时重签新鲜签名）或 url（退回，可能已过期）
      - str：旧格式，已是某段 url（可能已过期），原样返回
    """
    if isinstance(value, dict):
        aid = value.get("asset_id")
        if isinstance(aid, str) and aid:
            return sign_content_url(aid)
        u = value.get("url")
        if isinstance(u, str) and u:
            return u
        return None
    if isinstance(value, str) and value:
        return value
    return None


def _to_preview(t: GenerationTask) -> dict[str, Any]:
    """把一条生成任务转成作品预览项（含主资产 url / 封面 / 格数）。

    主资产 url 用持久化的 asset_id 实时重签，保证 `<img>` 直接加载不缺签。
    """
    out: dict[str, Any] = {
        "id": t.id,
        "task_type": t.task_type,
        "model": t.model,
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    if not t.result:
        return out
    try:
        r = json.loads(t.result)
    except (json.JSONDecodeError, TypeError):
        return out
    if not isinstance(r, dict):
        return out
    out["progress"] = r.get("progress") if isinstance(r.get("progress"), (int, float)) else None
    # 主资产：顶层 result 直接含 asset_id + url（非嵌套 dict），需分开处理
    aid = r.get("asset_id")
    if isinstance(aid, str) and aid:
        out["asset_url"] = sign_content_url(aid)
    else:
        u = r.get("url")
        out["asset_url"] = u if isinstance(u, str) and u else None
    out["prompt"] = r.get("prompt") if isinstance(r.get("prompt"), str) else None
    out["title"] = r.get("title") if isinstance(r.get("title"), str) else None
    comic = r.get("comic")
    if isinstance(comic, dict):
        if isinstance(comic.get("title"), str):
            out["title"] = comic.get("title")
        cover = comic.get("cover")
        if isinstance(cover, dict):
            # 封面用 asset_id 实时重签
            out["cover_url"] = _asset_fresh_url(cover)
        assets = comic.get("assets")
        if isinstance(assets, list):
            out["panel_count"] = len(assets)
    return out


_ACTIVE_STATUSES = ("queued", "processing")


@router.get("/recent")
async def recent_works(
    limit: int = Query(default=12, ge=1, le=120),
    task_type: str | None = Query(default=None, description="逗号分隔多选，如 image,comic"),
    status: str | None = Query(
        default="succeeded",
        description="succeeded(默认) | active(queued+processing) | failed | all",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    """当前用户最近媒体生成任务（作品库数据源，支持类型/状态过滤）。

    - status=succeeded（默认）：仅成功产物（兼容旧行为）
    - status=active：进行中任务（作品库「进行中」视图，供前端轮询）
    - status=all：全部状态；status=failed：仅失败
    """
    stmt = select(GenerationTask).where(
        GenerationTask.user_id == user.id,
        GenerationTask.task_type.in_(_MEDIA_TYPES),
    )
    s = (status or "succeeded").strip().lower()
    if s == "active":
        stmt = stmt.where(GenerationTask.status.in_(_ACTIVE_STATUSES))
    elif s == "failed":
        stmt = stmt.where(GenerationTask.status == "failed")
    elif s != "all":
        stmt = stmt.where(GenerationTask.status == "succeeded")
    types = [t.strip() for t in (task_type or "").split(",") if t.strip()]
    if types:
        stmt = stmt.where(GenerationTask.task_type.in_(types))
    rows = (
        (
            await db.execute(
                stmt.order_by(GenerationTask.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    items = [_to_preview(t) for t in rows]
    return {"success": True, "items": items}
