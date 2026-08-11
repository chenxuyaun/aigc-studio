"""FastMCP 实例与工具定义（stdio 与 /mcp HTTP 共用）。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, cast

from mcp.server.fastmcp import FastMCP
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.providers.base import TextProvider

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.asset import Asset
from app.models.generation_task import GenerationTask
from app.models.prompt import Prompt
from app.services.media_access import sign_content_url
from app.tasks.register_batch import _create_task_record, schedule_register_batch

mcp = FastMCP("aigc-studio", streamable_http_path="/")

_MAX_POLL_SECONDS = 300


def _task_dict(t: GenerationTask) -> dict[str, Any]:
    return {
        "id": t.id,
        "task_type": t.task_type,
        "status": t.status,
        "progress": t.progress,
        "model": t.model,
        "error": t.error_message or None,
    }


def _summarize_task_result(t: GenerationTask) -> dict[str, Any]:
    """任务终态摘要：主资产 url + comic 封面/格数。"""
    out = _task_dict(t)
    if not t.result:
        return out
    try:
        r = json.loads(t.result)
    except json.JSONDecodeError:
        return out
    out["asset_url"] = r.get("url")
    comic = r.get("comic")
    if isinstance(comic, dict):
        out["title"] = comic.get("title")
        cover = comic.get("cover")
        if isinstance(cover, dict):
            out["cover_url"] = cover.get("url")
        assets = comic.get("assets")
        if isinstance(assets, list):
            out["panel_count"] = len(assets)
    return out


async def _admin_user_id(db: AsyncSession) -> str:
    """stdio 模式默认用户：admin。"""
    from app.models.user import User

    row = (
        await db.execute(
            select(User).where(User.username == settings.INITIAL_ADMIN_USERNAME).limit(1)
        )
    ).scalar_one_or_none()
    return str(row.id) if row else ""


async def _request_role(ctx: Any | None) -> str:
    """解析调用者角色（admin 校验用）；查不到返回空串。"""
    from app.models.user import User

    uid = await _request_user_id(ctx)
    if not uid:
        return ""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        return str(row.role) if row else ""


async def _request_user_id(ctx: Any | None) -> str:
    """从 MCP 请求上下文解析调用者 user_id（按用户隔离工具操作）。

    优先级：内部透传 ctx.user_id（服务内工具循环）→ HTTP 请求 Bearer JWT 的 sub
    → stdio 模式（python -m app.mcp）无请求 → 回退 admin（系统级调用）。
    """
    if ctx is not None:
        uid = getattr(ctx, "user_id", None)
        if uid:
            return str(uid)
        if getattr(ctx, "request", None) is not None:
            try:
                headers = getattr(ctx.request, "headers", None)
                if headers is not None:
                    auth = headers.get("authorization", "")
                    if str(auth).lower().startswith("bearer "):
                        from app.core.security import verify_token

                        payload = verify_token(str(auth).split(" ", 1)[1])
                        if payload and payload.get("type") == "access" and payload.get("sub"):
                            return str(payload["sub"])
            except Exception:
                pass
    async with AsyncSessionLocal() as db:
        return await _admin_user_id(db)


@mcp.tool()
async def list_tasks(
    status: str = "",
    task_type: str = "",
    limit: int = 20,
    ctx: Any | None = None,
) -> list[dict[str, Any]]:
    """查询任务中心（可按状态/类型过滤；非 admin 仅本人任务）。"""
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        me = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        stmt = select(GenerationTask).order_by(GenerationTask.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(GenerationTask.status == status)
        if task_type:
            stmt = stmt.where(GenerationTask.task_type == task_type)
        if me is None or me.role != "admin":
            stmt = stmt.where(GenerationTask.user_id == uid)
        rows = (await db.execute(stmt)).scalars().all()
        return [_task_dict(t) for t in rows]


@mcp.tool()
async def get_task(task_id: str, ctx: Any | None = None) -> dict[str, Any]:
    """查询单个任务详情（含结果摘要；非 admin 仅本人任务）。"""
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        me = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        t = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
        if t is None:
            return {"error": f"任务不存在: {task_id}"}
        if (me is None or me.role != "admin") and t.user_id != uid:
            return {"error": "无权访问该任务"}
        return _summarize_task_result(t)


@mcp.tool()
async def list_assets(limit: int = 20, ctx: Any | None = None) -> list[dict[str, Any]]:
    """素材库最近资产列表（仅本人素材）。"""
    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        rows = (
            (
                await db.execute(
                    select(Asset).where(Asset.user_id == uid).order_by(Asset.id.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "asset_id": a.id,
                "filename": a.filename,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "url": sign_content_url(str(a.id)),
                "task_id": a.task_id,
            }
            for a in rows
        ]


@mcp.tool()
async def get_asset(asset_id: str, ctx: Any | None = None) -> dict[str, Any]:
    """查询素材详情（返回 content 下载路径；仅本人素材）。"""
    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        a = (await db.execute(select(Asset).where(Asset.id == asset_id))).scalar_one_or_none()
        if a is None:
            return {"error": f"素材不存在: {asset_id}"}
        if a.user_id != uid:
            return {"error": "无权访问该素材"}
        return {
            "asset_id": a.id,
            "filename": a.filename,
            "mime_type": a.mime_type,
            "size_bytes": a.size_bytes,
            "url": sign_content_url(str(a.id)),
            "task_id": a.task_id,
        }


@mcp.tool()
async def search_prompts(
    query: str,
    limit: int = 10,
    ctx: Any | None = None,
) -> list[dict[str, Any]]:
    """检索 prompt 库（标题/内容模糊匹配；仅公开或本人）。"""
    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        like = f"%{query}%"
        rows = (
            (
                await db.execute(
                    select(Prompt)
                    .where(
                        or_(Prompt.is_public.is_(True), Prompt.author_id == uid),
                        Prompt.title.like(like) | Prompt.content.like(like),
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [
            {"id": p.id, "title": p.title, "content": p.content[:500], "type": p.prompt_type}
            for p in rows
        ]


@mcp.tool()
async def get_upstream_status(ctx: Any | None = None) -> dict[str, Any]:
    """上游状态：grok 账号池 / 注册机 / grok 图片 / cpa（仅 admin）。"""
    if await _request_role(ctx) != "admin":
        return {"error": "仅管理员可查看上游状态"}
    from app.api.v1.upstream import upstream_status

    async with AsyncSessionLocal() as db:
        return await upstream_status(db)


@mcp.tool()
async def list_workflows(ctx: Any | None = None) -> list[dict[str, Any]]:
    """workflow 模板列表（公开或本人）。"""
    from app.models.workflow import Workflow

    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        rows = (
            (
                await db.execute(
                    select(Workflow)
                    .where(or_(Workflow.is_public.is_(True), Workflow.author_id == uid))
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": w.id,
                "name": w.name,
                "description": w.description,
            }
            for w in rows
        ]


def _fuzzy_like(col: Any, query: str) -> Any:
    """整体 LIKE 或 词级 OR 匹配（容错长 query/中英混合），配合词命中数排序。"""
    whole = f"%{query}%"
    words = [w for w in query.replace(":", " ").replace(",", " ").split() if len(w) >= 2]
    cond_whole = col.like(whole)
    if words:
        cond_words = or_(*[col.like(f"%{w}%") for w in words])
        return or_(cond_whole, cond_words)
    return cond_whole


def _word_score(col: Any, query: str) -> Any:
    """查询词命中数（用于排序，让全词命中的条目排前）。"""
    words = [w for w in query.replace(":", " ").replace(",", " ").split() if len(w) >= 2]
    if not words:
        return None
    return sum(col.like(f"%{w}%") for w in words)


@mcp.tool()
async def search_agent_directory(
    query: str = "",
    category: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """检索开源 AI Agent 项目目录（AgentList 1463 个项目）：按名称/描述/标签搜索，
    可按分类过滤（如 agent-framework / Coding Agent / RAG Tools）。选型参考用。"""
    from app.models.agentlist import AgentProject

    async with AsyncSessionLocal() as db:
        stmt = select(AgentProject)
        if query:
            stmt = stmt.where(
                or_(
                    _fuzzy_like(AgentProject.name, query),
                    _fuzzy_like(AgentProject.description, query),
                    _fuzzy_like(AgentProject.tags, query),
                )
            )
        if category:
            stmt = stmt.where(AgentProject.categories.like(f"%{category}%"))
        order: Any = AgentProject.stars.desc()
        score = _word_score(AgentProject.name, query) if query else None
        if score is not None:
            order = (score.desc(), AgentProject.stars.desc())
        stmt = stmt.order_by(*order).limit(min(limit, 10))
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "name": p.name,
                "stars": p.stars,
                "language": p.language,
                "license": p.license,
                "github_url": p.github_url,
                "description": p.description,
            }
            for p in rows
        ]


@mcp.tool()
async def get_agent_comparison(query: str = "") -> list[dict[str, Any]]:
    """查 Agent 框架对比表（如 LangChain vs CrewAI）：按标题搜索 31 组 PK 对比。"""
    from app.models.agentlist import AgentComparison

    async with AsyncSessionLocal() as db:
        stmt = select(AgentComparison)
        if query:
            stmt = stmt.where(
                or_(
                    _fuzzy_like(AgentComparison.title, query),
                    _fuzzy_like(AgentComparison.description, query),
                )
            )
        order: Any = AgentComparison.title.asc()
        score = _word_score(AgentComparison.title, query) if query else None
        if score is not None:
            order = (score.desc(), AgentComparison.title.asc())
        rows = (await db.execute(stmt.order_by(*order).limit(3))).scalars().all()
        return [
            {
                "title": c.title,
                "projects": c.projects,
                "description": c.description,
                "content": c.content,
            }
            for c in rows
        ]


async def _poll_task(task_id: str, timeout_seconds: float = _MAX_POLL_SECONDS) -> dict[str, Any]:
    """轮询任务到终态（succeeded/failed/cancelled），超时返回当前状态。"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        async with AsyncSessionLocal() as db:
            t = (
                await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
            ).scalar_one_or_none()
            if t is None:
                return {"error": f"任务不存在: {task_id}"}
            if t.status in ("succeeded", "failed", "cancelled"):
                return _summarize_task_result(t)
        if loop.time() >= deadline:
            return _task_dict(t) | {"note": "超时未完成，请稍后用 get_task 查询"}
        await asyncio.sleep(2)


async def _create_and_poll(
    task_type: str,
    model: str,
    params: Any,
    timeout_seconds: float = _MAX_POLL_SECONDS,
) -> dict[str, Any]:
    """创建媒体任务并轮询到终态。"""
    from app.services.generation_service import create_media_task

    async with AsyncSessionLocal() as db:
        user_id = await _admin_user_id(db)
        if not user_id:
            return {"error": "未找到 admin 用户，无法创建任务"}
        task = await create_media_task(
            db, user_id=user_id, task_type=task_type, model=model, params=params
        )
        task_id = task.id
    return await _poll_task(task_id, timeout_seconds)


@mcp.tool()
async def generate_image(prompt: str, model: str = "") -> dict[str, Any]:
    """文生图：grok-imagine-image。返回任务结果（含 asset_url）。"""
    from app.schemas.generation import ImageGenerationRequest

    params = ImageGenerationRequest(prompt=prompt, model=model or "grok-imagine-image")
    return await _create_and_poll("image", params.model, params)


@mcp.tool()
async def generate_comic(
    prompt: str,
    panels: int = 4,
    style: str = "日式漫画",
    characters: str = "",
    layout: str = "grid",
) -> dict[str, Any]:
    """漫画生成：分镜→逐格出图→封面+拼合。返回 title/cover_url/panel_count。"""
    from app.schemas.generation import ComicGenerationRequest

    params = ComicGenerationRequest(
        prompt=prompt,
        panels=panels,
        style=style,
        characters=characters,
        layout=layout,
        model="grok-imagine-image",
    )
    return await _create_and_poll("comic", params.model, params)


@mcp.tool()
async def generate_text(prompt: str, model: str = "") -> dict[str, Any]:
    """文本生成（默认 gpt-oss-120b-medium）。返回生成内容。"""
    from app.services.provider_resolver import resolve_text_provider

    try:
        async with AsyncSessionLocal() as db:
            resolved = await resolve_text_provider(db, model or settings.DEFAULT_TEXT_PROVIDER)
            provider = cast("TextProvider", resolved.provider)
            result = await provider.generate(prompt, resolved.model)
        return {
            "model": resolved.model,
            "provider": result.provider,
            "text": result.content[:4000],
        }
    except Exception as exc:
        return {"error": str(exc)[:300]}


@mcp.tool()
async def synthesize_speech(text: str, voice: str = "default") -> dict[str, Any]:
    """语音合成（edge-tts）。返回音频 asset_url。"""
    from app.schemas.generation import AudioGenerationRequest

    params = AudioGenerationRequest(text=text, voice=voice)
    return await _create_and_poll("audio", params.model, params)


@mcp.tool()
async def trigger_register_batch(count: int = 10, ctx: Any | None = None) -> dict[str, Any]:
    """触发注册机刷号批次（仅 admin，后台异步执行）。"""
    if await _request_role(ctx) != "admin":
        return {"error": "仅管理员可触发注册批次"}
    if not 1 <= count <= 20:
        return {"error": "run_count 需在 1-20 之间"}
    task_id = _create_task_record(count)
    schedule_register_batch(task_id, count)
    return {"ok": True, "task_id": task_id, "run_count": count}


# ==== Story Forge 创作工具（供 agent/角色技能工具循环调用） ====


@mcp.tool()
async def read_bible(project_id: str, ctx: Any | None = None) -> dict[str, Any]:
    """读取创作项目的故事圣经：梗概/类型/角色设定/大纲/已写章节摘要。"""
    from app.services import story_forge

    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        project = await story_forge.get_project(db, uid, project_id)
        if project is None:
            return {"error": f"项目不存在: {project_id}"}
        chapters = await story_forge.list_chapters(db, uid, project_id)
        chars = await story_forge.list_story_characters(db, uid, project_id)
        return {
            "id": project.id,
            "title": project.title,
            "genre": project.genre,
            "synopsis": project.synopsis,
            "status": project.status,
            "characters": chars,
            "chapters": [
                {
                    "chapter_no": c["chapter_no"],
                    "title": c["title"],
                    "outline": c["outline"],
                    "status": c["status"],
                    "content_preview": c["content"][:300],
                }
                for c in chapters
            ],
        }


@mcp.tool()
async def write_chapter(
    project_id: str,
    chapter_no: int,
    content: str,
    title: str = "",
    ctx: Any | None = None,
) -> dict[str, Any]:
    """把正文写入指定章节（创作工具：agent/角色提交自己的章节内容）。"""
    from app.services import story_forge

    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        chapters = await story_forge.list_chapters(db, uid, project_id)
        target = next((c for c in chapters if c["chapter_no"] == chapter_no), None)
        if target is None:
            chapter = await story_forge.create_chapter(
                db, uid, project_id, chapter_no=chapter_no, title=title
            )
            target = story_forge._chapter_dict(chapter)
        fields: dict[str, object] = {"content": content}
        if title:
            fields["title"] = title
        updated = await story_forge.update_chapter(db, uid, target["id"], fields)
        wc = updated.word_count if updated else 0
        return {"ok": True, "chapter_id": target["id"], "word_count": wc}


@mcp.tool()
async def update_character_state(
    project_id: str, character_id: str, state: str, ctx: Any | None = None
) -> dict[str, Any]:
    """更新故事角色的当前状态（剧务/主编推进角色弧线用）。"""
    from app.services import story_forge

    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        updated = await story_forge.update_story_character(
            db, uid, character_id, {"current_state": state}
        )
        if updated is None:
            return {"error": f"角色实例不存在: {character_id}"}
        return {"ok": True, "character_id": character_id, "current_state": state}


@mcp.tool()
async def list_outline(project_id: str, ctx: Any | None = None) -> list[dict[str, Any]]:
    """列出创作项目的章节大纲（含状态）。"""
    from app.services import story_forge

    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        chapters = await story_forge.list_chapters(db, uid, project_id)
        return [
            {
                "chapter_no": c["chapter_no"],
                "title": c["title"],
                "outline": c["outline"],
                "status": c["status"],
            }
            for c in chapters
        ]


@mcp.tool()
async def check_story_consistency(
    project_id: str, model: str = "", ctx: Any | None = None
) -> dict[str, Any]:
    """全书一致性审查：扫描已完成章节，检查角色名/时间线/事实物品/伏笔设定四类矛盾，
    返回结构化报告（通过项 + 问题清单 + 修改建议）。创作团队校稿用。"""
    from app.services import story_crew

    async with AsyncSessionLocal() as db:
        uid = await _request_user_id(ctx)
        return await story_crew.run_crew(db, uid, project_id, "consistency", model=model)


def _openai_tools() -> list[dict[str, Any]]:
    """FastMCP 工具注册表 → OpenAI function calling 格式。"""
    tools: list[dict[str, object]] = []
    try:
        listed = mcp._tool_manager.list_tools()
    except Exception:
        return tools
    for t in listed:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.parameters,
                },
            }
        )
    return tools


async def _call_tool(name: str, arguments: dict[str, Any]) -> str:
    """执行 MCP 工具并返回文本结果（供 agent 工具循环使用）。"""
    try:
        result = await mcp.call_tool(name, arguments)
        if hasattr(result, "content") and result.content:
            parts = []
            for block in result.content:
                if getattr(block, "type", "") == "text":
                    parts.append(str(getattr(block, "text", "")))
            return "\n".join(parts) if parts else json.dumps(arguments, ensure_ascii=False)
        return str(result)
    except Exception as exc:
        return f"工具执行失败: {exc}"
