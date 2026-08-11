"""Story Forge 创作引擎 API：项目 / 章节 / 角色实例 / 创作团队 / 连载 / 导出。

把角色扮演升级为内容创作基础设施：
- 创作项目（story bible）：角色卡 + 项目级世界书 + 章节 + 角色实例
- 章节生成：叙事模式（作者视角）/ 剧本模式（群聊引擎）/ 流式 / 任务化
- 创作团队（crew）：主编 / 作家 / 校对 / 剧务
- 自动连载（serial）：定时生成下一章
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.security.auth import get_current_user
from app.services import story_crew, story_forge
from app.services.provider_resolver import resolve_text_provider

router = APIRouter()


def _sse(ev: dict[str, Any]) -> str:
    """SSE data 行（统一 ensure_ascii=False）。"""
    return "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"


# ==== 请求模型 ====


class ProjectCreateRequest(BaseModel):
    title: str
    synopsis: str = ""
    genre: str = ""
    character_asset_ids: list[str] = Field(default_factory=list)
    settings: dict[str, Any] | None = None


class ProjectUpdateRequest(BaseModel):
    title: str | None = None
    synopsis: str | None = None
    genre: str | None = None
    status: str | None = None
    character_asset_ids: list[str] | None = None
    settings: dict[str, Any] | None = None


class CompassUpdateRequest(BaseModel):
    """创作罗盘：intent=全书承诺（题材/卖点/必须保留/必须避免），focus=当前阶段目标。"""

    intent: str = Field(default="", max_length=2000)
    focus: str = Field(default="", max_length=500)


class ChapterCreateRequest(BaseModel):
    chapter_no: int | None = None
    title: str = ""
    outline: str = ""


class ChapterUpdateRequest(BaseModel):
    title: str | None = None
    outline: str | None = None
    content: str | None = None
    status: str | None = None


class ChapterGenerateRequest(BaseModel):
    project_id: str
    model: str = ""
    max_tokens: int | None = None
    temperature: float | None = None
    instruction: str = ""
    mode: str = "narrative"  # narrative / script
    rounds: int = 6
    tool_loop: bool = False  # 允许模型调用 MCP 工具（技能/创作工具）


class StoryCharacterCreateRequest(BaseModel):
    name: str
    character_asset_id: str | None = None
    role: str = "supporting"
    description: str = ""
    goals: str = ""
    arc: str = ""
    current_state: str = ""
    skill_ids: list[str] = Field(default_factory=list)


class StoryCharacterUpdateRequest(BaseModel):
    name: str | None = None
    character_asset_id: str | None = None
    role: str | None = None
    description: str | None = None
    goals: str | None = None
    arc: str | None = None
    current_state: str | None = None
    skill_ids: list[str] | None = None


class SerialScheduleRequest(BaseModel):
    interval_minutes: int = 30
    batch_size: int = 1
    mode: str = "narrative"
    status: str = "active"


class CrewRunRequest(BaseModel):
    project_id: str
    stage: str  # director / writer / editor / stagehand
    chapter_id: str | None = None
    model: str = ""


# ==== 项目 ====


@router.get("/projects")
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    items = await story_forge.list_projects(db, user.id)
    return {"items": items}


@router.post("/projects")
async def create_project(
    req: ProjectCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    p = await story_forge.create_project(
        db,
        user.id,
        title=req.title,
        synopsis=req.synopsis,
        genre=req.genre,
        character_asset_ids=req.character_asset_ids,
        settings=req.settings,
    )
    return {"ok": True, "project": story_forge._project_dict(p)}


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    p = await story_forge.get_project(db, user.id, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"project": story_forge._project_dict(p)}


@router.put("/projects/{project_id}")
async def update_project(
    project_id: str,
    req: ProjectUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    p = await story_forge.update_project(db, user.id, project_id, req.model_dump(exclude_none=True))
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"ok": True, "project": story_forge._project_dict(p)}


@router.put("/projects/{project_id}/compass")
async def update_compass(
    project_id: str,
    req: CompassUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创作罗盘：全书承诺 + 当前阶段目标（注入每次生成，防多轮跑偏）。"""
    p = await story_forge.update_project(
        db,
        user.id,
        project_id,
        {"settings": {"compass": {"intent": req.intent.strip(), "focus": req.focus.strip()}}},
    )
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"ok": True, "project": story_forge._project_dict(p)}


class WritingStyleExtractRequest(BaseModel):
    """从指定章节提取写法特征。"""

    chapter_id: str = Field(min_length=1, max_length=64)


class WritingStyleUpdateRequest(BaseModel):
    """手动编辑/启停写法特征池。"""

    features: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/projects/{project_id}/writing-style")
async def extract_writing_style_route(
    project_id: str,
    req: WritingStyleExtractRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """从指定章节提炼写法特征（存项目 settings，注入后续章节生成）。"""
    result = await story_forge.extract_writing_style(db, user.id, project_id, req.chapter_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.put("/projects/{project_id}/writing-style")
async def update_writing_style_route(
    project_id: str,
    req: WritingStyleUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动编辑/启停写法特征（每条 {name, desc, enabled}）。"""
    cleaned = []
    for f in (req.features or [])[:5]:
        if isinstance(f, dict):
            cleaned.append(
                {
                    "name": str(f.get("name") or "特征")[:12],
                    "desc": str(f.get("desc") or "")[:120],
                    "enabled": bool(f.get("enabled", True)),
                }
            )
    p = await story_forge.update_project(
        db, user.id, project_id, {"settings": {"writing_style": cleaned}}
    )
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"ok": True, "features": cleaned}


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ok = await story_forge.delete_project(db, user.id, project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"ok": True}


@router.get("/projects/{project_id}/bible")
async def project_bible(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """故事圣经聚合视图：项目 + 章节摘要（不含全文）+ 角色实例（供编辑/生成上下文）。

    章节全文由 GET /story/chapters/{id} 单独拉取，避免全书 payload 一次传输。
    """
    p = await story_forge.get_project(db, user.id, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "project": story_forge._project_dict(p),
        "chapters": await story_forge.list_chapters(db, user.id, project_id, summary=True),
        "characters": await story_forge.list_story_characters(db, user.id, project_id),
    }


@router.post("/projects/{project_id}/outline")
async def generate_outline(
    project_id: str,
    chapters: int = Query(8, ge=1, le=40),
    model: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """按梗概 + 角色设定生成全章大纲并批量创建章节。"""
    result = await story_forge.generate_outline(
        db, user.id, project_id, chapters=chapters, model=model
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/projects/{project_id}/crew")
async def run_crew(
    project_id: str,
    req: CrewRunRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创作团队阶段：director / writer / editor / stagehand。"""
    result = await story_crew.run_crew(
        db, user.id, project_id, req.stage, chapter_id=req.chapter_id, model=req.model
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/projects/{project_id}/export")
async def export_project(
    project_id: str,
    format: str = Query("markdown", pattern="^(markdown|jsonl|epub)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """导出整本：markdown / jsonl / epub。"""
    result = await story_forge.export_project(db, user.id, project_id, fmt=format)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    from urllib.parse import quote

    filename = result["filename"]
    if result.get("binary"):
        return Response(
            content=result["content"],
            media_type="application/epub+zip",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=\"story.epub\"; filename*=UTF-8''{quote(filename)}"
                )
            },
        )
    media_type = (
        "text/markdown; charset=utf-8"
        if format == "markdown"
        else "application/jsonl; charset=utf-8"
    )
    return StreamingResponse(
        iter([result["content"]]),
        media_type=media_type,
        headers={
            # 中文文件名：RFC 5987 编码 + ASCII 兜底（starlette 不允许非 ASCII header）
            "Content-Disposition": (
                f"attachment; filename=\"story.md\"; filename*=UTF-8''{quote(filename)}"
            )
        },
    )


# ==== 章节 ====


@router.get("/projects/{project_id}/chapters")
async def list_chapters(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"items": await story_forge.list_chapters(db, user.id, project_id)}


@router.get("/projects/{project_id}/search")
async def search_project(
    project_id: str,
    q: str = Query("", min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """项目内搜索：章节/梗概 + 本人知识库文档（编辑器「查找前文」用）。"""
    from app.services.local_search import search_project as _search_project

    items = await _search_project(db, user.id, project_id, q, limit=limit)
    return {
        "query": q,
        "items": [
            {
                "scope": r.scope,
                "id": r.id,
                "title": r.title,
                "snippet": r.snippet,
                "score": r.score,
                "meta": r.meta,
            }
            for r in items
        ],
        "total": len(items),
    }


@router.post("/projects/{project_id}/chapters")
async def create_chapter(
    project_id: str,
    req: ChapterCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    c = await story_forge.create_chapter(
        db,
        user.id,
        project_id,
        chapter_no=req.chapter_no,
        title=req.title,
        outline=req.outline,
    )
    return {"ok": True, "chapter": story_forge._chapter_dict(c)}


@router.get("/chapters/{chapter_id}")
async def get_chapter(
    chapter_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    c = await story_forge.get_chapter(db, user.id, chapter_id)
    if c is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"chapter": story_forge._chapter_dict(c)}


@router.put("/chapters/{chapter_id}")
async def update_chapter(
    chapter_id: str,
    req: ChapterUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    c = await story_forge.update_chapter(db, user.id, chapter_id, req.model_dump(exclude_none=True))
    if c is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"ok": True, "chapter": story_forge._chapter_dict(c)}


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(
    chapter_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ok = await story_forge.delete_chapter(db, user.id, chapter_id)
    if not ok:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"ok": True}


@router.post("/chapters/{chapter_id}/generate")
async def generate_chapter(
    chapter_id: str,
    req: ChapterGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """生成章节正文（同步）：mode=narrative 叙事 / script 剧本。"""
    if req.mode == "script":
        result = await story_forge.generate_chapter_script(
            db,
            user.id,
            req.project_id,
            chapter_id,
            rounds=req.rounds,
            model=req.model,
            max_tokens=req.max_tokens,
        )
    else:
        result = await story_forge.generate_chapter(
            db,
            user.id,
            req.project_id,
            chapter_id,
            model=req.model,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            instruction=req.instruction,
            tool_loop=req.tool_loop,
        )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/chapters/{chapter_id}/generate/task")
async def generate_chapter_task(
    chapter_id: str,
    req: ChapterGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """生成章节正文（任务化，后台执行，前端轮询 /tasks/{id}）。"""
    from app.models.generation_task import GenerationTask
    from app.tasks.story_tasks import _dispatch_story

    task = GenerationTask(
        task_type="chapter",
        status="queued",
        model=req.model or "",
        params=json.dumps(
            {
                "project_id": req.project_id,
                "chapter_id": chapter_id,
                "mode": req.mode,
                "rounds": req.rounds,
                "instruction": req.instruction,
                "tool_loop": req.tool_loop,
            },
            ensure_ascii=False,
        ),
        user_id=user.id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    _dispatch_story(task.id)
    return {"ok": True, "task": {"id": task.id, "status": task.status, "task_type": task.task_type}}


@router.post("/chapters/{chapter_id}/generate/stream")
async def generate_chapter_stream(
    chapter_id: str,
    req: ChapterGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """生成章节正文（SSE 流式，叙事模式）。"""
    import re as _re

    from app.services import roleplay as rp

    async def _gen() -> AsyncIterator[str]:
        project = await story_forge.get_project(db, user.id, req.project_id)
        chapter = await story_forge.get_chapter(db, user.id, chapter_id)
        if project is None or chapter is None:
            yield _sse({"type": "error", "error": "项目或章节不存在"})
            return
        cards = await rp._load_cards(
            db, user.id, story_forge._load_json(project.character_asset_ids, [])
        )
        if not cards:
            yield _sse({"type": "error", "error": "项目未关联角色卡"})
            return
        system_prompt, user_prompt, wb = await story_forge._build_chapter_prompt(
            db, user.id, project, chapter, cards, req.instruction
        )
        resolved = await resolve_text_provider(db, req.model)
        provider = rp.cast_text_provider(resolved.provider)
        chunks: list[str] = []
        try:
            async for chunk in provider.stream_generate(
                user_prompt,
                resolved.model,
                system=system_prompt,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            ):
                chunks.append(chunk)
                yield _sse({"type": "chunk", "content": chunk})
                # 断点恢复：每 20 个 chunk 增量落库草稿（status=draft），
                # 刷新/断网后章节保留已生成部分，可继续编辑或重新生成
                if len(chunks) % 20 == 0:
                    chapter.content = "".join(chunks)
                    chapter.status = "draft"
                    await db.commit()
        except Exception as exc:
            # 中断：保留草稿（不丢已生成内容）
            if chunks:
                chapter.content = "".join(chunks)
                chapter.status = "draft"
                await db.commit()
            yield _sse({"type": "error", "error": f"生成失败：{str(exc)[:200]}"})
            yield "data: [DONE]\n\n"
            return
        content = "".join(chunks).strip()
        names = [c.get("name") or "角色" for _, c in cards]
        content = _re.sub(rf"^第\s*{chapter.chapter_no}\s*章.*?\n", "", content, count=1).strip()
        scripts = await rp._load_regex_scripts(db, user.id)
        if scripts:
            content = rp._apply_regex(scripts, content, "ai_output", names)
        chapter.content = content
        chapter.word_count = len(content)
        chapter.model = resolved.model
        chapter.status = "done"
        await db.commit()
        # AI 腔体检（分级报告：套话/机械句式/连接词/宣传腔/空洞修饰）
        try:
            from app.services.ai_voice_checker import check_ai_voice

            issues = check_ai_voice(content)
        except Exception:
            issues = []
        yield _sse(
            {
                "type": "done",
                "chapter_id": chapter.id,
                "word_count": chapter.word_count,
                "worldbook_hits": len(wb.activated),
                "ai_voice": issues[:12],
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/chapters/{chapter_id}/versions")
async def chapter_versions(
    chapter_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """章节版本历史（快照列表，新→旧）。"""
    versions = await story_forge.list_chapter_versions(db, user.id, chapter_id)
    return {"items": versions}


@router.post("/chapters/{chapter_id}/restore")
async def restore_chapter(
    chapter_id: str,
    version_id: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """还原章节到指定版本（当前内容先自动快照）。"""
    result = await story_forge.restore_chapter_version(db, user.id, chapter_id, version_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/chapters/{chapter_id}/revise")
async def revise_chapter(
    chapter_id: str,
    instruction: str = Query(..., min_length=1),
    model: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """按指令修订章节正文。"""
    result = await story_forge.revise_chapter(db, user.id, chapter_id, instruction, model=model)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ==== 故事角色实例 ====


@router.get("/projects/{project_id}/characters")
async def list_story_characters(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {"items": await story_forge.list_story_characters(db, user.id, project_id)}


@router.post("/projects/{project_id}/characters")
async def create_story_character(
    project_id: str,
    req: StoryCharacterCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    s = await story_forge.create_story_character(
        db,
        user.id,
        project_id,
        name=req.name,
        character_asset_id=req.character_asset_id,
        role=req.role,
        description=req.description,
        goals=req.goals,
        arc=req.arc,
        current_state=req.current_state,
        skill_ids=req.skill_ids,
    )
    return {"ok": True, "character": story_forge._story_char_dict(s)}


@router.put("/characters/{character_id}")
async def update_story_character(
    character_id: str,
    req: StoryCharacterUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    s = await story_forge.update_story_character(
        db, user.id, character_id, req.model_dump(exclude_none=True)
    )
    if s is None:
        raise HTTPException(status_code=404, detail="角色实例不存在")
    return {"ok": True, "character": story_forge._story_char_dict(s)}


@router.delete("/characters/{character_id}")
async def delete_story_character(
    character_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ok = await story_forge.delete_story_character(db, user.id, character_id)
    if not ok:
        raise HTTPException(status_code=404, detail="角色实例不存在")
    return {"ok": True}


# ==== 自动连载 ====


@router.get("/projects/{project_id}/schedules")
async def list_schedules(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.serial_schedule import SerialSchedule

    rows = (
        (
            await db.execute(
                select(SerialSchedule).where(
                    SerialSchedule.project_id == project_id,
                    SerialSchedule.user_id == user.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": s.id,
                "project_id": s.project_id,
                "interval_minutes": s.interval_minutes,
                "batch_size": s.batch_size,
                "next_run_at": str(s.next_run_at) if s.next_run_at else "",
                "chapter_count": s.chapter_count,
                "status": s.status,
                "mode": s.mode,
                "last_run_at": str(s.last_run_at) if s.last_run_at else "",
                "error_message": s.error_message,
            }
            for s in rows
        ]
    }


@router.post("/projects/{project_id}/schedules")
async def create_schedule(
    project_id: str,
    req: SerialScheduleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    from app.models.serial_schedule import SerialSchedule

    p = await story_forge.get_project(db, user.id, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    now = datetime.now(UTC)
    s = SerialSchedule(
        project_id=project_id,
        user_id=user.id,
        interval_minutes=req.interval_minutes,
        batch_size=req.batch_size,
        mode=req.mode,
        status=req.status,
        next_run_at=now + timedelta(minutes=req.interval_minutes),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return {
        "ok": True,
        "schedule": {
            "id": s.id,
            "project_id": s.project_id,
            "interval_minutes": s.interval_minutes,
            "next_run_at": str(s.next_run_at),
            "status": s.status,
            "mode": s.mode,
        },
    }


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    req: SerialScheduleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.serial_schedule import SerialSchedule

    s = (
        await db.execute(
            select(SerialSchedule).where(
                SerialSchedule.id == schedule_id, SerialSchedule.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="调度不存在")
    s.interval_minutes = req.interval_minutes
    s.batch_size = req.batch_size
    s.mode = req.mode
    s.status = req.status
    await db.commit()
    return {"ok": True}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.serial_schedule import SerialSchedule

    s = (
        await db.execute(
            select(SerialSchedule).where(
                SerialSchedule.id == schedule_id, SerialSchedule.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="调度不存在")
    await db.delete(s)
    await db.commit()
    return {"ok": True}
