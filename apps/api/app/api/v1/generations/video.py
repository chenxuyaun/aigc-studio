from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.data.schemas.generation import VideoGenerationRequest
from app.models.user import User
from app.schemas.generation import TaskResponse
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


class StoryboardRequest(BaseModel):
    """剧本影视化：章节 → 分镜提示词 → 批量视频任务。"""

    chapter_id: str
    scenes: int = Field(default=8, ge=1, le=12)
    model: str = ""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _parse_scene_json(raw: str, want: int) -> list[dict[str, str]]:
    """从模型输出里提取 [{title, prompt}] 数组；失败返回空列表。"""
    text = (raw or "").strip()
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    scenes: list[dict[str, str]] = []
    for it in data[:want]:
        if isinstance(it, dict) and (str(it.get("title") or "").strip() or str(it.get("prompt") or "").strip()):
            scenes.append(
                {
                    "title": str(it.get("title") or "").strip()[:80] or f"分镜 {len(scenes) + 1}",
                    "prompt": str(it.get("prompt") or it.get("description") or "").strip(),
                }
            )
    return scenes


async def _split_chapter_fallback(chapter: Any, want: int, context: str = "") -> list[dict[str, str]]:
    """LLM 拆解失败时的兜底：按段落切分章节内容（context 仅为镜头前缀，不含原文）。"""
    del context
    body = (chapter.content or "").strip()
    if not body:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", body) if len(p.strip()) > 12]
    if not paras:
        paras = [body[:400]]
    out: list[dict[str, str]] = []
    for i, p in enumerate(paras[:want]):
        out.append(
            {
                "title": f"分段 {i + 1}",
                "prompt": f"根据小说章节改编的镜头画面：{p}"[:400],
            }
        )
    return out


@router.post("/storyboard")
async def video_storyboard(
    req: StoryboardRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """把故事章节拆成分镜提示词，并逐一创建视频生成任务。

    分镜文本由 hub 文本链 LLM 产出（面向 Wan2.1 的镜头级视觉描述）；
    每个分镜创建独立 video 任务（160 节点 ComfyUI 串行出片）。
    """
    from app.applications.provider_resolver import resolve_text_provider
    from app.applications.story_forge import get_chapter
    from app.applications.roleplay import cast_text_provider

    chapter = await get_chapter(db, user.id, req.chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    body = (chapter.content or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="该章节还没有正文，请先在故事页生成正文")
    context = (
        f"小说《{chapter.title or '未命名'}》第 {chapter.chapter_no} 章。"
        f"原文（仅作素材，不要直接搬进画面描述）：\n{body[:2000]}"
    )
    system_prompt = (
        "你是影视分镜导演。把给定的小说章节拆解成连续的分镜镜头，每次一颗镜头的画面。\n"
        "要求：\n"
        "1. 镜头按故事时间线排序，覆盖章节主要情节；\n"
        "2. 每个分镜只写『画面』：主体动作/场景环境/镜头运动/光线氛围，20-60 字中文，不要对白，不要心理描写；\n"
        "3. 画面描述要具体可画（如“古旧书屋内，烛光摇曳，少女指尖滑过尘封的书脊”），不要出现章节标题；\n"
        "4. 输出必须是 JSON 数组，每项 {\"title\": \"镜头标题\", \"prompt\": \"画面描述\"}，不要输出其他文字。"
    )
    resolved = await resolve_text_provider(db, req.model)
    provider = cast_text_provider(resolved.provider)
    try:
        result = await provider.generate(
            context, resolved.model, system=system_prompt, max_tokens=2048
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"分镜生成失败：{str(exc)[:160]}") from exc
    scenes = _parse_scene_json(result.content or "", req.scenes)
    if not scenes:
        scenes = await _split_chapter_fallback(chapter, req.scenes)

    tasks: list[dict[str, str]] = []
    for scene in scenes:
        task = await create_media_task(
            db,
            user_id=user.id,
            task_type="video",
            model="",
            params=VideoGenerationRequest(model="", prompt=scene["prompt"], duration=5),
        )
        tasks.append(
            {
                "title": scene["title"],
                "prompt": scene["prompt"],
                "task_id": task.id,
                "status": task.status,
            }
        )
    return {
        "ok": True,
        "project_id": chapter.project_id,
        "chapter_id": chapter.id,
        "scenes": tasks,
    }