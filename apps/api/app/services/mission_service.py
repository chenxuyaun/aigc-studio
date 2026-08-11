"""Mission 任务总控（AGI Orchestrator 内核）：目标 → LLM 拆解 → 逐步骤执行 → 汇总。

阶段 1 范围：串行执行 ≤4 步，复用现有同步能力（写歌/文本/图片/视频任务/联网检索）。
核心循环：perceive(目标) → plan(拆解) → execute(调度) → observe(结果) → summarize(汇总)。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.text_utils import extract_json, result_text

_PLAN_PROMPT = """你是任务总控大脑（AGI Orchestrator）。把用户的目标拆解成可执行的多步计划。
规则：
- 步骤类型 kind 只能是：music（写一首歌）/ text（生成文本内容）/ image（生成图片）/
  video（生成视频）/ comic（生成漫画）/ search（联网检索资料）/ agent（调用 Agent 库中的智能体执行）
/
  story（写一段故事章节）/ asmr（从 ASMR 库检索音频素材）/
  character（让角色扮演中的角色以角色口吻回应）/ memory（查询角色的记忆档案）/
  code（生成可运行的代码文件）
- 1-4 步；每步一个具体产出（prompt 用中文写清楚生成要求）
- 若某步需要上一步的产出作为素材（如先检索再写），该步加 "input": "prev"
- 创作/整理/分析类步骤建议指派 Agent：加 "agent": "角色名"（如「民谣词人」「资料猎手」
  ——执行器找不到该角色时会按名字现场创建专属 Agent，无需预建团队）
- character/memory 步骤可加 "char": "角色名"（角色库中的角色）
输出 JSON（不要任何多余文字）
：
{{"plan": [{{"kind": "music", "prompt": "主题描述", "title": "这步产出的名称", "reason": "
为什么用这个引擎（1
句
话
）
"
,
 "input": "prev或省略"}}]}}

用户目标：{goal}

{profile_block}
{agents_block}
{lessons_block}"""

_LESSON_PROMPT = """你从刚才的任务执行中提炼一条「创作教训」（Reflection），供下次任务避免重犯。
规则：一句话说清失败原因 + 一句下次怎么做；50 字内。
输出 JSON（不要任何多余文字）：{{"lesson": "…"}}

目标：{goal}
失败步骤：{failed}"""

_KIND_LABELS = {
    "music": "🎵 写歌",
    "text": "✍️ 文本",
    "image": "🖼 图片",
    "video": "🎬 视频",
    "comic": "📚 漫画",
    "search": "🔍 检索",
    "agent": "🤖 Agent",
    "story": "📖 故事",
    "asmr": "🎧 ASMR 素材",
    "character": "🎭 角色",
    "memory": "📒 记忆",
    "code": "💻 代码",
}

_CODE_PROMPT = """你是资深软件工程师。根据需求生成可运行的代码项目文件。
规则：
- 输出 1-3 个文件（项目越简单越好，优先单文件可运行）
- 每个文件 ≤3000 字；代码完整可运行，包含必要注释
- 优先 Python/Flask、HTML/JS 单页等轻量方案
输出 JSON（不要任何多余文字）：
{{"files": [{{"path": "app.py", "content": "完整代码"}}], "note": "运行方式（1 句话）"}}

需求：{prompt}"""

_STORY_SYSTEM = """你是小说执笔作者。规则：
- 第三人称叙事，一段只写一个场景，动作最多 2 个
- 必须有具体的「戏剧时刻」：一个人、一次交汇、一件小事
- 细节落地（谁在哪儿、做什么、闻到什么、摸到什么），禁止抽象空转
- 单章 800-1500 字，有起承转合；只输出正文本身"""


async def _available_agents(db: AsyncSession, user_id: str) -> list[dict[str, str]]:
    """可用 Agent（Identity 摘要）：供 Orchestrator 规划时选择。"""
    from sqlalchemy import select

    from app.models.agent import Agent

    rows = (
        (
            await db.execute(
                select(Agent)
                .where((Agent.author_id == user_id) | (Agent.is_public.is_(True)))
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(a.id),
            "name": str(a.name or "")[:40],
            "desc": str(a.description or "")[:80],
        }
        for a in rows
    ]


async def _recent_lessons(db: AsyncSession, user_id: str, limit: int = 5) -> list[str]:
    """最近教训（Reflection 记忆）：供 plan 注入，避免重犯。"""
    from sqlalchemy import select

    from app.models.mission_lesson import MissionLesson

    rows = (
        (
            await db.execute(
                select(MissionLesson)
                .where(MissionLesson.user_id == user_id)
                .order_by(MissionLesson.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [str(r.lesson) for r in rows if str(r.lesson).strip()]


async def _save_lessons(db: AsyncSession, user_id: str, goal: str, lessons: list[str]) -> None:
    from app.models.mission_lesson import MissionLesson

    for lesson in lessons:
        if lesson.strip():
            db.add(MissionLesson(user_id=user_id, goal=goal[:500], lesson=lesson.strip()))
    await db.commit()


async def plan_mission(db: AsyncSession, user_id: str, goal: str) -> list[dict[str, Any]]:
    """LLM 拆解目标 → 计划（失败返回空计划，调用方降级为单步 text）。

    注入历史教训（Reflection 记忆）+ 可用 Agent 列表（Multi-Agent 规划）。
    """
    from app.services.provider_resolver import resolve_text_provider

    lessons = await _recent_lessons(db, user_id)
    lessons_block = (
        "\n【历史教训】（本平台此前任务中沉淀，规划时必须避免重犯）\n"
        + "\n".join(f"- {item}" for item in lessons)
        if lessons
        else ""
    )
    agents = await _available_agents(db, user_id)
    agents_block = (
        "\n【可用 Agent】（kind=agent 时从中选择，agent 字段填 Agent 名）\n"
        + "\n".join(f"- {a['name']}：{a['desc']}" for a in agents)
        if agents
        else ""
    )
    from app.services.profile_service import build_profile_text

    profile_block = await build_profile_text(db, user_id)
    if profile_block:
        profile_block = "\n" + profile_block
    resolved = await resolve_text_provider(db, "")
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        _PLAN_PROMPT.format(
            goal=goal[:500],
            profile_block=profile_block,
            agents_block=agents_block,
            lessons_block=lessons_block,
        ),
        resolved.model,
        temperature=0.4,
    )
    data = extract_json(result_text(result))
    plan = []
    for step in (data.get("plan") or [])[:4]:
        kind = str(step.get("kind") or "").strip()
        if kind not in _KIND_LABELS:
            continue
        plan.append(
            {
                "kind": kind,
                "prompt": str(step.get("prompt") or "")[:500],
                "title": str(step.get("title") or _KIND_LABELS[kind])[:40],
                "input": "prev" if str(step.get("input") or "") == "prev" else "",
                "agent": str(step.get("agent") or "").strip()[:40],
                "char": str(step.get("char") or "").strip()[:40],
                "reason": str(step.get("reason") or "").strip()[:100],
            }
        )
    return plan


async def _spawn_mission_agent(
    db: AsyncSession, user_id: str, name: str, task: str
) -> Any | None:
    """现场招人：按角色名创建专属 Agent（同名已存在则复用，零 LLM 开销）。"""

    from sqlalchemy import select

    from app.models.agent import Agent

    try:
        existed = (
            (
                await db.execute(
                    select(Agent).where(Agent.name == name).limit(1)
                )
            )
            .scalars()
            .first()
        )
        if existed is not None:
            return existed
        agent = Agent(
            name=name[:200],
            description=f"Mission 现场编排创建的角色 Agent（任务：{task[:80]}）",
            system_prompt=(
                f"你是「{name}」，本任务中的角色专家。\n"
                f"任务主题：{task[:300]}\n"
                "规则：输出直接可用、贴合用户目标的内容；结构清晰；不空谈。"
            ),
            agent_type="mission",
            is_public=False,
            author_id=user_id,
            source_type="mission",
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        return agent
    except Exception:
        return None


async def _execute_agent(
    db: AsyncSession, user_id: str, prompt: str, agent_name: str = ""
) -> dict[str, Any]:
    """Agent Runtime 执行器：加载 Agent（Identity）→ 注入 Goal + Memory → 生成 → 留痕。

    Agent Instance = Identity（system_prompt）+ Goal（本步任务）+ Memory（教训/素材）
                    + Tools（agent.tools）+ State（agent_runs 留痕）。
    """
    from sqlalchemy import select

    from app.models.agent import Agent
    from app.services.provider_resolver import resolve_text_provider

    query = select(Agent).where((Agent.author_id == user_id) | (Agent.is_public.is_(True)))
    if agent_name:
        query = query.where(Agent.name == agent_name)
    agent = (await db.execute(query.order_by(Agent.use_count.desc()).limit(1))).scalars().first()
    if agent is None and agent_name:
        # 编排水位：Orchestrator 指派的角色不存在 → 现场创建专属 Agent（无需预建团队）
        agent = await _spawn_mission_agent(db, user_id, agent_name, prompt)
    if agent is None:
        return {"summary": f"未找到可用 Agent（{agent_name or '任意'}）", "ok": False}
    agent_id = str(agent.id)
    try:
        lessons = await _recent_lessons(db, user_id, limit=3)
        memory_block = (
            "\n\n【平台教训】（避免重犯）\n" + "\n".join(f"- {item}" for item in lessons)
            if lessons
            else ""
        )
        resolved = await resolve_text_provider(db, str(agent.model or ""))
        system_prompt = f"{agent.system_prompt}\n【本次任务目标】{prompt}{memory_block}"
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt,
            resolved.model,
            system=system_prompt,
            temperature=agent.temperature if agent.temperature is not None else 0.7,
        )
        text = result_text(result).strip()
        # State 留痕 + 使用计数
        from app.models.agent_run import AgentRun

        db.add(
            AgentRun(
                user_id=user_id,
                agent_id=agent_id,
                goal=prompt[:500],
                result=text[:3000],
                status="done" if text else "failed",
            )
        )
        agent.use_count = int(agent.use_count or 0) + 1
        await db.commit()
        return {
            "summary": f"🤖 {agent.name}：{text[:500]}",
            "ok": bool(text),
            "agent_id": agent_id,
            "agent": agent.name,
        }
    except Exception as exc:
        return {"summary": f"Agent 执行失败：{str(exc)[:120]}", "ok": False}


async def _execute_text(
    db: AsyncSession, user_id: str, prompt: str, agent_name: str = ""
) -> dict[str, Any]:
    from app.services.provider_resolver import resolve_text_provider

    role_block = await _agent_role_block(db, user_id, agent_name, prompt)
    gen_prompt = f"{role_block}{prompt}" if role_block else prompt
    resolved = await resolve_text_provider(db, "")
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        gen_prompt, resolved.model, temperature=0.7
    )
    text = result_text(result).strip()
    return {"summary": text[:600], "ok": bool(text)}


async def _agent_role_block(
    db: AsyncSession, user_id: str, agent_name: str, task: str
) -> str:
    """角色编排：加载/现场创建 Agent，返回注入创作提示的角色设定（无则空串）。"""
    if not agent_name:
        return ""
    agent = await _spawn_mission_agent(db, user_id, agent_name, task)
    if agent is None:
        return ""
    return (
        f"（以「{agent.name}」的角色视角创作。角色设定："
        f"{str(agent.system_prompt or '')[:200]}）\n"
    )


async def _execute_music(
    db: AsyncSession, user_id: str, prompt: str, theme_goal: str = "", agent_name: str = ""
) -> dict[str, Any]:
    from app.api.v1.generations.music import MusicComposeRequest, _auto_save_work, compose_song

    # 角色编排：指派了 Agent 则以其身份视角创作（引擎完整链路保留）
    role_block = await _agent_role_block(db, user_id, agent_name, prompt)
    theme_prompt = f"{role_block}{prompt}" if role_block else prompt
    theme_prompt = theme_prompt[:500]  # MusicComposeRequest.theme 上限 500
    req = MusicComposeRequest(
        theme=theme_prompt, style="", mood="", language="zh", verse_count=2, model=""
    )
    data = await compose_song(req, db, cast(Any, user_id))
    if data.get("error"):
        return {"summary": f"写歌失败：{data['error']}", "ok": False}
    title = str(data.get("title") or "未命名")
    lyrics = str(data.get("lyrics") or "")[:300]
    # 落库主题优先取用户原始目标（步骤 prompt 是执行细节，不适合当作品主题）
    theme = (theme_goal or prompt)[:500]
    try:
        # 生长闭环：Mission 产出的歌也进作品库（source=mission）
        await _auto_save_work(
            db,
            user_id=user_id,
            theme=theme,
            style=str(data.get("style") or ""),
            final=data,
            rounds=[],
            source="mission",
        )
        _spawn_work_backfill(user_id, title, theme, data)
    except Exception:
        pass  # 入库失败不影响 Mission 结果
    return {"summary": f"《{title}》\n{lyrics}", "ok": True}


# 后台回填任务引用（防 GC；done_callback 丢弃引用，满足 RUF006）
_backfill_tasks: set[asyncio.Task[Any]] = set()


def _spawn_work_backfill(
    user_id: str, title: str, theme: str, data: dict[str, Any]
) -> None:
    """把 Mission 产出的好歌词后台回填知识库（异常静默；防刷由回填函数把关）。"""

    from app.api.v1.generations.music import _backfill_work_material

    async def _run() -> None:
        with contextlib.suppress(Exception):
            await _backfill_work_material(
                user_id=user_id,
                work_title=title,
                theme=theme[:500],
                lyrics=str(data.get("lyrics") or ""),
                chords=str(data.get("chords") or ""),
                arrangement=str(data.get("arrangement") or ""),
            )

    task = asyncio.create_task(_run())
    task.add_done_callback(_backfill_tasks.discard)
    _backfill_tasks.add(task)


async def _execute_code(db: AsyncSession, user_id: str, prompt: str) -> dict[str, Any]:
    """代码生成引擎：LLM 产出可运行文件集（files: [{path, content}]）。"""
    from app.services.provider_resolver import resolve_text_provider

    resolved = await resolve_text_provider(db, "")
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        _CODE_PROMPT.format(prompt=prompt[:800]), resolved.model, temperature=0.3
    )
    data = extract_json(result_text(result))
    files = []
    for f in (data.get("files") or [])[:3]:
        path = str(f.get("path") or "").strip()[:80]
        content = str(f.get("content") or "").strip()
        if path and content:
            files.append({"path": path, "content": content})
    if not files:
        return {"summary": "代码生成失败（无有效文件）", "ok": False}
    note = str(data.get("note") or "").strip()[:200]
    summary = "💻 生成 " + "、".join(f["path"] for f in files)
    if note:
        summary += f"\n运行方式：{note}"
    return {
        "summary": summary[:400],
        "ok": True,
        "code": files,  # 完整代码（存 run results，前端 artifacts 展示）
    }


async def _execute_media_task(
    db: AsyncSession, user_id: str, task_type: str, prompt: str
) -> dict[str, Any]:
    from pydantic import BaseModel as _BM

    from app.services.generation_service import create_media_task

    class _MediaParams(_BM):
        prompt: str = ""
        model: str = ""

    try:
        task = await create_media_task(
            db,
            user_id=user_id,
            task_type=task_type,
            model="",
            params=_MediaParams(prompt=prompt, model=""),
            project_id=None,
        )
        return {
            "summary": f"已提交{_KIND_LABELS.get(task_type, task_type)}任务（{task.id[:8]}…），可到任务中心查看进度",  # noqa: E501
            "ok": True,
            "task_id": task.id,
        }
    except Exception as exc:
        return {"summary": f"任务提交失败：{str(exc)[:120]}", "ok": False}


async def _execute_character(
    db: AsyncSession, user_id: str, prompt: str, char_name: str = ""
) -> dict[str, Any]:
    """角色扮演引擎融合：让角色卡实例回应（Identity=角色卡，Goal=本次发言）。"""
    from sqlalchemy import select

    from app.models.roleplay_character import RoleplayCharacter
    from app.services.provider_resolver import resolve_text_provider

    query = select(RoleplayCharacter).where(RoleplayCharacter.user_id == user_id)
    if char_name:
        query = query.where(RoleplayCharacter.name == char_name)
    char = (await db.execute(query.limit(1))).scalars().first()
    if char is None:
        return {"summary": "未找到角色卡，请先创建角色", "ok": False}
    try:
        parts = [str(char.description or ""), str(char.personality or "")]
        card_text = "\n".join(p for p in parts if p)[:800]
        system_prompt = (
            f"你是角色「{char.name}」：{card_text}\n"
            f"{char.system_prompt or ''}"
            "用这个角色的口吻、性格与说话习惯回应，不跳出角色。"
        )
        resolved = await resolve_text_provider(db, "")
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt, resolved.model, system=system_prompt, temperature=0.9
        )
        text = result_text(result).strip()
        return {"summary": f"🎭 {char.name}：{text[:500]}", "ok": bool(text)}
    except Exception as exc:
        return {"summary": f"角色回应失败：{str(exc)[:120]}", "ok": False}


async def _execute_memory(
    db: AsyncSession, user_id: str, prompt: str, char_name: str = ""
) -> dict[str, Any]:
    """记忆系统融合：查询角色记忆/档案（L3 画像 + 原著档案摘要）。"""
    from sqlalchemy import select

    from app.models.character_profile import CharacterProfile
    from app.models.roleplay_character import RoleplayCharacter

    query = select(RoleplayCharacter).where(RoleplayCharacter.user_id == user_id)
    if char_name:
        query = query.where(RoleplayCharacter.name == char_name)
    char = (await db.execute(query.limit(1))).scalars().first()
    if char is None:
        return {"summary": "未找到角色卡，无法查询记忆", "ok": False}
    profile = (
        await db.execute(select(CharacterProfile).where(CharacterProfile.asset_id == char.asset_id))
    ).scalar_one_or_none()
    if profile is None or not (profile.identity or profile.personality or profile.speech_style):
        return {"summary": "该角色尚无记忆档案（可在角色扮演-记忆面板做原著蒸馏）", "ok": False}
    lines = []
    for label, val in (
        ("身份", profile.identity),
        ("性格", profile.personality),
        ("说话风格", profile.speech_style),
    ):
        if val:
            lines.append(f"{label}：{str(val)[:150]}")
    return {"summary": f"📒 {char.name} 记忆档案：\n" + "\n".join(lines)[:600], "ok": True}


async def _execute_search(db: AsyncSession, user_id: str, prompt: str) -> dict[str, Any]:
    from app.services.knowledge_materials import _digest_web_results
    from app.services.web_search import search_web

    items = await search_web(prompt, limit=3)
    if not items:
        return {"summary": "联网检索无结果", "ok": False}
    notes = await _digest_web_results(db, prompt, items)
    return {"summary": (notes or "检索完成（无提炼要点）")[:600], "ok": True}


async def _execute_story(db: AsyncSession, user_id: str, prompt: str) -> dict[str, Any]:
    """Story Forge 引擎融合：Mission 内生成故事章节（叙事铁律 + 落地铁律）。"""
    from app.services.provider_resolver import resolve_text_provider

    resolved = await resolve_text_provider(db, "")
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        prompt, resolved.model, system=_STORY_SYSTEM, temperature=0.85
    )
    text = result_text(result).strip()
    return {"summary": text[:800], "ok": bool(text)}


async def _execute_asmr(db: AsyncSession, user_id: str, prompt: str) -> dict[str, Any]:
    """ASMR 聚合库融合：按主题检索 ASMR 作品作为素材（标题/社团/标签）。"""
    from sqlalchemy import select

    from app.models.asmr_work import AsmrWork

    rows = (
        (
            await db.execute(
                select(AsmrWork)
                .where(
                    AsmrWork.title.like(f"%{prompt[:30]}%") | AsmrWork.tags.like(f"%{prompt[:30]}%")
                )
                .order_by(AsmrWork.dl_count.desc())
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {"summary": "ASMR 库未命中该主题", "ok": False}
    import json as _json

    lines = []
    for w in rows:
        tags = ""
        with contextlib.suppress(Exception):
            tags = "、".join(
                str(t.get("zh") or t.get("name") or "") for t in _json.loads(w.tags or "[]")
            )[:60]
        lines.append(f"《{w.title[:40]}》（{w.circle_name[:20]}）下载:{w.dl_count} 标签:{tags}")
    return {"summary": "\n".join(lines)[:600], "ok": True}


async def execute_step(
    db: AsyncSession,
    user_id: str,
    step: dict[str, Any],
    prev_summary: str = "",
    goal: str = "",
) -> dict[str, Any]:
    """执行单步计划（kind → 现有能力；input=prev 时把上一步产出注入 prompt）。"""
    kind = step.get("kind", "")
    prompt = str(step.get("prompt") or "").strip()
    if prev_summary and step.get("input") == "prev":
        prompt = f"{prompt}\n\n（上一步的产出，作为本步素材参考）\n{prev_summary[:800]}"
    try:
        if kind == "agent":
            return await _execute_agent(db, user_id, prompt, str(step.get("agent") or ""))
        if kind == "music":
            return await _execute_music(
                db, user_id, prompt, theme_goal=goal, agent_name=str(step.get("agent") or "")
            )
        if kind == "text":
            return await _execute_text(
                db, user_id, prompt, agent_name=str(step.get("agent") or "")
            )
        if kind == "image":
            return await _execute_media_task(db, user_id, "image", prompt)
        if kind == "video":
            return await _execute_media_task(db, user_id, "video", prompt)
        if kind == "comic":
            return await _execute_media_task(db, user_id, "comic", prompt)
        if kind == "search":
            return await _execute_search(db, user_id, prompt)
        if kind == "story":
            return await _execute_story(db, user_id, prompt)
        if kind == "asmr":
            return await _execute_asmr(db, user_id, prompt)
        if kind == "character":
            return await _execute_character(db, user_id, prompt, str(step.get("char") or ""))
        if kind == "memory":
            return await _execute_memory(db, user_id, prompt, str(step.get("char") or ""))
        if kind == "code":
            return await _execute_code(db, user_id, prompt)
    except Exception as exc:
        return {"summary": f"执行失败：{str(exc)[:120]}", "ok": False}
    return {"summary": "未知步骤类型", "ok": False}


async def _reflect_lessons(
    db: AsyncSession, user_id: str, goal: str, results: list[dict[str, Any]]
) -> None:
    """Reflection：任务有失败步骤时，LLM 提炼教训并沉淀（平台从失败中学习）。"""
    failed = [
        f"步骤{r.get('step')}({r.get('kind')})：{str(r.get('summary') or '')[:100]}"
        for r in results
        if not r.get("ok")
    ]
    if not failed:
        return
    from app.services.provider_resolver import resolve_text_provider

    try:
        resolved = await resolve_text_provider(db, "")
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            _LESSON_PROMPT.format(goal=goal[:300], failed="\n".join(failed)[:600]),
            resolved.model,
            temperature=0.3,
        )
        data = extract_json(result_text(result))
        lesson = str(data.get("lesson") or "").strip()
        if lesson:
            await _save_lessons(db, user_id, goal, [lesson])
    except Exception:
        pass


async def execute_plan(
    db: AsyncSession,
    user_id: str,
    goal: str,
    plan: list[dict[str, Any]],
    parent_run_id: str = "",
) -> dict[str, Any]:
    """按给定计划执行（人工干预模式：计划由用户确认/调整后提交）。

    与 run_mission 共用同一执行循环（结果传递/反思/持久化），仅计划来源不同。
    """
    # 白名单 + 结构规范化（防越权 kind / 超长字段）
    cleaned: list[dict[str, Any]] = []
    for s in plan[:4]:
        kind = str(s.get("kind") or "").strip()
        if kind not in _KIND_LABELS:
            continue
        cleaned.append(
            {
                "kind": kind,
                "prompt": str(s.get("prompt") or "")[:500],
                "title": str(s.get("title") or _KIND_LABELS[kind])[:40],
                "input": "prev" if str(s.get("input") or "") == "prev" else "",
                "agent": str(s.get("agent") or "").strip()[:40],
                "char": str(s.get("char") or "").strip()[:40],
                "reason": str(s.get("reason") or "").strip()[:100],
            }
        )
    if not cleaned:
        # 降级：目标直接作为单步文本生成
        cleaned = [{"kind": "text", "prompt": goal, "title": "✍️ 直接生成", "input": ""}]
    plan = cleaned
    results: list[dict[str, Any]] = []
    prev_summary = ""
    for step in plan:
        outcome = await execute_step(db, user_id, step, prev_summary, goal)
        summary = str(outcome.get("summary") or "")
        results.append(
            {
                "step": len(results) + 1,
                "kind": step.get("kind", ""),
                "title": step.get("title", ""),
                "summary": summary,
                "ok": outcome.get("ok", False),
                "task_id": outcome.get("task_id", ""),
                "agent": str(step.get("agent") or "") or outcome.get("agent") or "",
                "code": outcome.get("code") or [],
            }
        )
        if outcome.get("ok") and summary:
            prev_summary = summary  # 结果传递：供 input=prev 的下一步使用
    ok_count = sum(1 for r in results if r["ok"])
    await _reflect_lessons(db, user_id, goal, results)
    mission = {
        "goal": goal,
        "plan": [
            {
                "step": i + 1,
                "kind": s.get("kind"),
                "title": s.get("title"),
                "reason": s.get("reason", ""),
            }
            for i, s in enumerate(plan)
        ],
        "results": results,
        "summary": f"共 {len(results)} 步，成功 {ok_count} 步"
        + ("" if ok_count == len(results) else "（失败步骤见明细，已沉淀教训）"),
    }
    await _save_run(db, user_id, goal, mission, parent_run_id)
    return mission


async def run_mission(
    db: AsyncSession, user_id: str, goal: str, parent_run_id: str = ""
) -> dict[str, Any]:
    """任务总控主循环：拆解 → 串行执行（结果传递）→ 汇总 → 反思沉淀教训 → 会话持久化。"""
    try:
        plan = await plan_mission(db, user_id, goal)
    except Exception:
        plan = []
    return await execute_plan(db, user_id, goal, plan, parent_run_id)


async def continue_mission(
    db: AsyncSession, user_id: str, run_id: str, message: str
) -> dict[str, Any] | None:
    """Mission 多轮对话：基于上次会话（目标+产出）延续迭代。

    组装「延续目标」→ 新一轮 run_mission（parent_run_id 关联成链）。
    找不到会话返回 None（调用方 404）。
    """
    parent = await get_run(db, user_id, run_id)
    if parent is None:
        return None
    prev_results = "；".join(
        f"步骤{i}({r.get('kind')})：{str(r.get('summary') or '')[:200]}"
        for i, r in enumerate(parent["results"], 1)
        if r.get("ok")
    )
    goal = (
        "继续上次任务并按下述要求迭代：\n"
        f"【上次目标】{parent['goal'][:400]}\n"
        f"【上次产出】{prev_results[:600] or '（无成功步骤）'}\n"
        f"【本次要求】{message[:300]}"
    )
    return await run_mission(db, user_id, goal, parent_run_id=run_id)


async def _save_run(
    db: AsyncSession, user_id: str, goal: str, mission: dict[str, Any], parent_run_id: str = ""
) -> str:
    """会话持久化：目标/计划/结果/汇总入库，返回 run_id。"""

    from app.models.mission_run import MissionRun

    run = MissionRun(
        user_id=user_id,
        goal=goal[:1000],
        plan=json.dumps(mission.get("plan") or [], ensure_ascii=False),
        results=json.dumps(mission.get("results") or [], ensure_ascii=False),
        summary=str(mission.get("summary") or "")[:200],
        parent_run_id=parent_run_id or None,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    mission["run_id"] = run.id
    return run.id


async def list_runs(db: AsyncSession, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """任务历史（长期协作记忆）：最近 N 次会话。"""

    from sqlalchemy import select

    from app.models.mission_run import MissionRun

    rows = (
        (
            await db.execute(
                select(MissionRun)
                .where(MissionRun.user_id == user_id)
                .order_by(MissionRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "goal": r.goal,
            "plan": json.loads(r.plan or "[]"),
            "results": json.loads(r.results or "[]"),
            "summary": r.summary,
            "parent_run_id": r.parent_run_id or "",
            "created_at": str(r.created_at) if r.created_at else "",
        }
        for r in rows
    ]


async def get_run(db: AsyncSession, user_id: str, run_id: str) -> dict[str, Any] | None:
    """单次会话完整回看。"""

    from sqlalchemy import select

    from app.models.mission_run import MissionRun

    r = (
        await db.execute(
            select(MissionRun).where(MissionRun.id == run_id, MissionRun.user_id == user_id)
        )
    ).scalar_one_or_none()
    if r is None:
        return None
    return {
        "id": r.id,
        "goal": r.goal,
        "plan": json.loads(r.plan or "[]"),
        "results": json.loads(r.results or "[]"),
        "summary": r.summary,
        "parent_run_id": r.parent_run_id or "",
        "created_at": str(r.created_at) if r.created_at else "",
    }
