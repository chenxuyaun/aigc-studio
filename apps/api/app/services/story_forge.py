"""Story Forge 创作引擎：以角色扮演的方式生成小说/剧本章节。

复用 roleplay 管线组件（不重造）：
- 角色卡：roleplay._load_cards（V2 全字段 + PNG 懒同步）
- 世界书：roleplay._load_lore_entries（支持 project 作用域）+ worldbook.match_worldbook
- 宏：macros.substitute；正则：roleplay._apply_regex；情绪：roleplay.extract_mood
- 群聊：roleplay._build_prompt(group=True)（说话者轮流 + nudge）→ 剧本模式

产出形态：
- narrative（叙事体）：角色设定驱动「作者视角」写小说正文
- script（剧本/对话体）：群聊引擎让角色轮流发言，拼装成对话流章节
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.models.story_chapter import StoryChapter
from app.models.story_character import StoryCharacter
from app.models.story_project import StoryProject
from app.models.text_document import TextDocument
from app.services import roleplay
from app.services.knowledge_retrieval import chunk_text, retrieve
from app.services.macros import substitute as substitute_macros
from app.services.provider_resolver import resolve_text_provider
from app.services.worldbook import estimate_tokens, match_worldbook

# 叙事模式上下文预算（token 估算：中文 len//2）
_HISTORY_BUDGET = 4000
_OUTLINE_CHAPTERS = 8


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError, TypeError:
        return default


# ==== 项目 CRUD ====


def _project_dict(p: StoryProject) -> dict[str, Any]:
    return {
        "id": p.id,
        "title": p.title,
        "synopsis": p.synopsis,
        "genre": p.genre,
        "status": p.status,
        "character_asset_ids": _load_json(p.character_asset_ids, []),
        "settings": _load_json(p.settings, {}),
        "created_at": str(p.created_at) if p.created_at else "",
        "updated_at": str(p.updated_at) if p.updated_at else "",
    }


async def list_projects(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(StoryProject)
                .where(StoryProject.user_id == user_id)
                .order_by(StoryProject.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    items = [_project_dict(p) for p in rows]
    if not items:
        return items
    # 聚合统计：每项目章节数 + 总字数
    stats = (
        await db.execute(
            select(
                StoryChapter.project_id,
                func.count(StoryChapter.id),
                func.coalesce(func.sum(StoryChapter.word_count), 0),
            )
            .where(StoryChapter.user_id == user_id)
            .group_by(StoryChapter.project_id)
        )
    ).all()
    stat_map = {pid: (count, words) for pid, count, words in stats}
    for item in items:
        count, words = stat_map.get(item["id"], (0, 0))
        item["chapter_count"] = count
        item["total_words"] = int(words)
    return items


async def get_project(db: AsyncSession, user_id: str, project_id: str) -> StoryProject | None:
    return (
        await db.execute(
            select(StoryProject).where(
                StoryProject.id == project_id, StoryProject.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def create_project(
    db: AsyncSession,
    user_id: str,
    *,
    title: str,
    synopsis: str = "",
    genre: str = "",
    character_asset_ids: list[str] | None = None,
    settings: dict[str, Any] | None = None,
) -> StoryProject:
    p = StoryProject(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title,
        synopsis=synopsis,
        genre=genre,
        character_asset_ids=json.dumps(character_asset_ids or [], ensure_ascii=False),
        settings=json.dumps(settings or {}, ensure_ascii=False),
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    # 自动为所选角色卡创建故事实例（名称取角色卡；纯文字占位稍后手动添加）
    for aid in character_asset_ids or []:
        card = await _card_by_asset(db, user_id, aid)
        if card:
            db.add(
                StoryCharacter(
                    id=str(uuid.uuid4()),
                    project_id=p.id,
                    user_id=user_id,
                    character_asset_id=aid,
                    name=str(card.get("name") or "角色"),
                )
            )
    await db.commit()
    await db.refresh(p)
    return p


async def _card_by_asset(db: AsyncSession, user_id: str, asset_id: str) -> dict[str, Any] | None:
    """读取角色卡结构化行（无则从 PNG 懒同步，复用 roleplay._load_cards）。"""
    from app.models.roleplay_character import RoleplayCharacter

    row = await db.get(RoleplayCharacter, asset_id)
    if row is not None:
        return {"name": row.name}
    cards = await roleplay._load_cards(db, user_id, [asset_id])
    return cards[0][1] if cards else None


async def update_project(
    db: AsyncSession, user_id: str, project_id: str, fields: dict[str, Any]
) -> StoryProject | None:
    p = await get_project(db, user_id, project_id)
    if p is None:
        return None
    for k, v in fields.items():
        if k in {"title", "synopsis", "genre", "status"}:
            setattr(p, k, v)
        elif k == "character_asset_ids":
            p.character_asset_ids = json.dumps(v or [], ensure_ascii=False)
        elif k == "settings":
            merged = _load_json(p.settings, {})
            merged.update(v or {})
            p.settings = json.dumps(merged, ensure_ascii=False)
    await db.commit()
    await db.refresh(p)
    return p


async def delete_project(db: AsyncSession, user_id: str, project_id: str) -> bool:
    p = await get_project(db, user_id, project_id)
    if p is None:
        return False
    for tbl in (StoryChapter, StoryCharacter):
        for row in (
            (await db.execute(select(tbl).where(tbl.project_id == project_id))).scalars().all()
        ):
            await db.delete(row)
    # 级联删除项目级世界书条目（避免孤儿数据）
    from app.models.roleplay_lore import RoleplayLoreEntry

    for lore in (
        (
            await db.execute(
                select(RoleplayLoreEntry).where(
                    RoleplayLoreEntry.project_id == project_id,
                    RoleplayLoreEntry.user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    ):
        await db.delete(lore)
    await db.delete(p)
    await db.commit()
    return True


# ==== 章节 CRUD ====


def _chapter_dict(c: StoryChapter) -> dict[str, Any]:
    return {
        "id": c.id,
        "project_id": c.project_id,
        "chapter_no": c.chapter_no,
        "title": c.title,
        "outline": c.outline,
        "content": c.content,
        "status": c.status,
        "word_count": c.word_count,
        "model": c.model,
        "task_id": c.task_id,
        "created_at": str(c.created_at) if c.created_at else "",
        "updated_at": str(c.updated_at) if c.updated_at else "",
    }


async def list_chapters(
    db: AsyncSession, user_id: str, project_id: str, *, summary: bool = False
) -> list[dict[str, Any]]:
    """章节列表。summary=True：content 只返回前 200 字摘要（bible 聚合用，避免全量 payload）。"""
    rows = (
        (
            await db.execute(
                select(StoryChapter)
                .where(StoryChapter.project_id == project_id, StoryChapter.user_id == user_id)
                .order_by(StoryChapter.chapter_no.asc())
            )
        )
        .scalars()
        .all()
    )
    items = [_chapter_dict(c) for c in rows]
    if summary:
        for it in items:
            content = str(it.get("content") or "")
            it["content_truncated"] = len(content) > 200
            it["content"] = content[:200]
    return items


async def get_chapter(db: AsyncSession, user_id: str, chapter_id: str) -> StoryChapter | None:
    return (
        await db.execute(
            select(StoryChapter).where(
                StoryChapter.id == chapter_id, StoryChapter.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def create_chapter(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    *,
    chapter_no: int | None = None,
    title: str = "",
    outline: str = "",
) -> StoryChapter:
    if chapter_no is None:
        chapter_no = (
            int(
                (
                    await db.execute(
                        select(func.max(StoryChapter.chapter_no)).where(
                            StoryChapter.project_id == project_id
                        )
                    )
                ).scalar()
                or 0
            )
            + 1
        )
    c = StoryChapter(
        id=str(uuid.uuid4()),
        project_id=project_id,
        user_id=user_id,
        chapter_no=chapter_no,
        title=title or f"第 {chapter_no} 章",
        outline=outline,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def update_chapter(
    db: AsyncSession, user_id: str, chapter_id: str, fields: dict[str, Any]
) -> StoryChapter | None:
    c = await get_chapter(db, user_id, chapter_id)
    if c is None:
        return None
    for k, v in fields.items():
        if k in {"title", "outline", "content", "status"}:
            setattr(c, k, v)
            if k == "content":
                c.word_count = len(str(v))
                if str(v).strip():
                    c.status = "done"
    await db.commit()
    await db.refresh(c)
    return c


async def delete_chapter(db: AsyncSession, user_id: str, chapter_id: str) -> bool:
    c = await get_chapter(db, user_id, chapter_id)
    if c is None:
        return False
    await db.delete(c)
    await db.commit()
    return True


# ==== 故事角色实例 CRUD ====


async def _placeholder_cards(
    db: AsyncSession, user_id: str, project: StoryProject
) -> list[tuple[str, dict[str, Any]]]:
    """占位角色卡：把 story_characters（文字角色）转成虚拟酒馆角色卡。

    项目未挂真实角色卡（PNG）时的回退——角色群的演绎仍可用，
    与酒馆角色卡的差异仅在于无 PNG 资产（prompt 组装完全一致）。
    """
    chars = await list_story_characters(db, user_id, project.id)
    if not chars:
        return []
    cards: list[tuple[str, dict[str, Any]]] = []
    for s in chars:
        desc = str(s["description"] or "")
        if s["goals"]:
            desc += "\n目标：" + s["goals"]
        if s["current_state"]:
            desc += "\n当前状态：" + s["current_state"]
        cards.append(
            (
                str(s["character_asset_id"] or ""),
                {
                    "name": s["name"] or "角色",
                    "description": desc,
                    "personality": str(s.get("arc") or ""),
                    "scenario": "",
                    "first_mes": "",
                    "mes_example": "",
                    "alternate_greetings": [],
                    "system_prompt": "",
                    "post_history_instructions": "",
                    "creator_notes": "",
                    "tags": [],
                    "character_book": {},
                    "talkativeness": 0.5,
                    "depth_prompt": {},
                },
            )
        )
    return cards


def _story_char_dict(s: StoryCharacter) -> dict[str, Any]:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "character_asset_id": s.character_asset_id,
        "name": s.name,
        "role": s.role,
        "description": s.description,
        "goals": s.goals,
        "arc": s.arc,
        "current_state": s.current_state,
        "skill_ids": _load_json(s.skill_ids, []),
    }


async def list_story_characters(
    db: AsyncSession, user_id: str, project_id: str
) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(StoryCharacter).where(
                    StoryCharacter.project_id == project_id, StoryCharacter.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    return [_story_char_dict(s) for s in rows]


async def create_story_character(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    *,
    name: str,
    character_asset_id: str | None = None,
    role: str = "supporting",
    description: str = "",
    goals: str = "",
    arc: str = "",
    current_state: str = "",
    skill_ids: list[str] | None = None,
) -> StoryCharacter:
    s = StoryCharacter(
        id=str(uuid.uuid4()),
        project_id=project_id,
        user_id=user_id,
        character_asset_id=character_asset_id,
        name=name,
        role=role,
        description=description,
        goals=goals,
        arc=arc,
        current_state=current_state,
        skill_ids=json.dumps(skill_ids or [], ensure_ascii=False),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def update_story_character(
    db: AsyncSession, user_id: str, character_id: str, fields: dict[str, Any]
) -> StoryCharacter | None:
    s = (
        await db.execute(
            select(StoryCharacter).where(
                StoryCharacter.id == character_id, StoryCharacter.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if s is None:
        return None
    for k, v in fields.items():
        if k in {
            "name",
            "role",
            "description",
            "goals",
            "arc",
            "current_state",
            "character_asset_id",
        }:
            setattr(s, k, v)
        elif k == "skill_ids":
            s.skill_ids = json.dumps(v or [], ensure_ascii=False)
    await db.commit()
    await db.refresh(s)
    return s


async def delete_story_character(db: AsyncSession, user_id: str, character_id: str) -> bool:
    s = (
        await db.execute(
            select(StoryCharacter).where(
                StoryCharacter.id == character_id, StoryCharacter.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if s is None:
        return False
    await db.delete(s)
    await db.commit()
    return True


# ==== bible 上下文组装 ====


async def _bible_text(
    db: AsyncSession,
    user_id: str,
    project: StoryProject,
    cards: list[tuple[str, dict[str, Any]]],
) -> str:
    """角色设定 + 故事实例定位/目标/弧线/当前状态 + 技能说明 → 注入文本。"""
    parts: list[str] = []
    chars = await list_story_characters(db, user_id, project.id)
    by_asset = {s["character_asset_id"]: s for s in chars if s["character_asset_id"]}
    skill_ids: set[str] = set()
    for s in chars:
        skill_ids.update(s["skill_ids"])
    skills: dict[str, Skill] = {}
    if skill_ids:
        for row in (await db.execute(select(Skill).where(Skill.id.in_(skill_ids)))).scalars().all():
            skills[row.id] = row
    for aid, card in cards:
        name = str(card.get("name") or "角色")
        inst = by_asset.get(aid)
        block = [f"【角色「{name}」】", f"外观背景：{card.get('description', '')}"]
        if card.get("personality"):
            block.append(f"性格：{card['personality']}")
        if inst:
            if inst["role"] == "protagonist":
                block.append("定位：主角")
            if inst["goals"]:
                block.append(f"目标：{inst['goals']}")
            if inst["arc"]:
                block.append(f"成长弧线：{inst['arc']}")
            if inst["current_state"]:
                block.append(f"当前状态：{inst['current_state']}")
        parts.append("\n".join(block))
    for s in chars:
        if not s["character_asset_id"] and s["name"]:
            parts.append(
                f"【角色「{s['name']}」】\n外观背景：{s['description']}"
                + (f"\n目标：{s['goals']}" if s["goals"] else "")
                + (f"\n当前状态：{s['current_state']}" if s["current_state"] else "")
            )
        for sid in s["skill_ids"]:
            sk = skills.get(sid)
            if sk and sk.instructions:
                parts.append(f"【技能·{sk.name}（{s['name']}可施展）】\n{sk.instructions}")
    return "\n\n".join(parts)


async def _story_history(
    db: AsyncSession, user_id: str, project: StoryProject
) -> tuple[list[dict[str, Any]], str]:
    """已完成章节 → 世界书扫描消息 + 上下文预算内的正文文本。"""
    rows = (
        (
            await db.execute(
                select(StoryChapter)
                .where(
                    StoryChapter.project_id == project.id,
                    StoryChapter.user_id == user_id,
                    StoryChapter.status == "done",
                )
                .order_by(StoryChapter.chapter_no.asc())
            )
        )
        .scalars()
        .all()
    )
    messages: list[dict[str, Any]] = []
    bodies: list[str] = []
    budget = _HISTORY_BUDGET
    for c in reversed(rows):
        body = str(c.content or "").strip()
        if not body:
            continue
        messages.insert(
            0,
            {"role": "assistant", "content": f"第{c.chapter_no}章 {c.title}\n{body[:2000]}"},
        )
        if estimate_tokens(body) <= budget:
            bodies.insert(0, f"【第{c.chapter_no}章 {c.title}】\n{body}")
            budget -= estimate_tokens(body)
        elif not bodies:
            bodies.append(f"【第{c.chapter_no}章 {c.title}（开头）】\n{body[:1500]}")
    return messages, "\n\n".join(bodies)


def _project_summary(project: StoryProject) -> str:
    return str(_load_json(project.settings, {}).get("summary") or "")


def _project_knowledge_doc_ids(project: StoryProject) -> list[str]:
    return [str(x) for x in (_load_json(project.settings, {}).get("knowledge_doc_ids") or [])]


async def _knowledge_refs(
    db: AsyncSession, user_id: str, project: StoryProject, query: str, max_chars: int = 800
) -> str:
    """按项目配置的知识库文档检索相关片段，拼成【参考资料】段（空则返回 ""）。"""
    doc_ids = _project_knowledge_doc_ids(project)
    if not doc_ids:
        return ""
    docs = (
        (
            await db.execute(
                select(TextDocument).where(
                    TextDocument.user_id == user_id, TextDocument.id.in_(doc_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    if not docs:
        return ""
    chunks = [(doc.id, doc.title, t) for doc in docs for t in chunk_text(doc.content or "")]
    hits = retrieve(chunks, query, top_k=4)
    if not hits:
        return ""
    budget = max_chars
    parts: list[str] = []
    used = 0
    for _doc_id, title, text, _score in hits:
        piece = f"【{title}】\n{text.strip()[:300]}"
        if used + len(piece) > budget:
            break
        parts.append(piece)
        used += len(piece)
    if not parts:
        return ""
    return "【参考资料（来自项目知识库，可引用其设定/规范）】\n" + "\n\n".join(parts)


async def _build_chapter_prompt(
    db: AsyncSession,
    user_id: str,
    project: StoryProject,
    chapter: StoryChapter,
    cards: list[tuple[str, dict[str, Any]]],
    instruction: str = "",
) -> tuple[str, str, Any]:
    """叙事模式 prompt 组装：返回 (system, user_prompt, worldbook_result)。

    供 generate_chapter 与流式端点复用（保证两条路径提示词一致）。
    """
    names = [c.get("name") or "角色" for _, c in cards]
    messages, history_text = await _story_history(db, user_id, project)
    recent_texts = [str(m.get("content") or "") for m in messages[-6:]]

    # 世界书（项目作用域）
    lore_entries = await roleplay._load_lore_entries(db, user_id, names, project.id)
    wb = match_worldbook(lore_entries, recent_texts, max_depth=6)
    ctx = roleplay._macro_context(cards, "作者", messages, current_input=instruction)
    wb_before = [substitute_macros(t, ctx) for t in wb.before]
    wb_after = [substitute_macros(t, ctx) for t in wb.after]

    bible = await _bible_text(db, user_id, project, cards)
    summary = _project_summary(project)

    parts: list[str] = [
        f"【创作任务】你是小说《{project.title}》的执笔作者（{project.genre or '类型未定'}）。",
    ]
    # 创作罗盘（全书承诺 + 当前阶段目标）：强制注入每次生成，防多轮跑偏/一致性漂移
    compass = _load_json(project.settings, {}).get("compass") or {}
    intent = str(compass.get("intent") or "").strip()
    focus = str(compass.get("focus") or "").strip()
    if intent or focus:
        compass_lines = []
        if intent:
            compass_lines.append(f"【全书承诺】（不可违反，每章都要守住）\n{intent}")
        if focus:
            compass_lines.append(f"【当前阶段目标】（本阶段最高优先级）\n{focus}")
        parts.append("\n".join(compass_lines))
    # 写法特征池（AI-Novel 借鉴）：已确认的写法特征，本章必须延续
    style_block = writing_style_block(project)
    if style_block:
        parts.append(style_block)
    if project.synopsis:
        parts.append(f"【故事梗概】\n{project.synopsis}")
    if wb_before:
        parts.append("【世界观（世界书·前置）】\n" + "\n".join(f"- {t}" for t in wb_before))
    parts.append("【角色设定】\n" + bible)
    if summary:
        parts.append(f"【前情摘要（保持连贯）】\n{summary}")
    if wb_after:
        parts.append("【世界观（世界书·后置）】\n" + "\n".join(f"- {t}" for t in wb_after))
    parts.append(
        "【写作要求】\n"
        "- 以第三人称叙事，场景/动作/对话自然流畅\n"
        "- 严格遵守世界观与角色设定，人物言行与性格一致\n"
        "- 单章 800-1500 字，有完整的起承转合\n"
        "- 只输出正文本身，不要输出标题、大纲或任何解释"
    )
    system_prompt = "\n\n".join(parts)

    user_parts: list[str] = []
    if history_text:
        user_parts.append("【已写章节（前文，保持情节连续）】\n" + history_text)
    if chapter.outline:
        user_parts.append(f"【本章大纲】\n{chapter.outline}")
    if instruction:
        user_parts.append(f"【本次写作指令】\n{instruction}")
    # 项目配置的知识库文档：检索相关片段注入（本格推理规范/方法论等）
    knowledge_refs = await _knowledge_refs(
        db,
        user_id,
        project,
        chapter.outline or project.synopsis or chapter.title,
    )
    if knowledge_refs:
        user_parts.append(knowledge_refs)
    user_parts.append(f"请撰写第 {chapter.chapter_no} 章《{chapter.title}》的正文：")
    user_prompt = "\n\n".join(user_parts)
    return system_prompt, user_prompt, wb


# ==== 叙事模式生成 ====


async def _chapter_tool_loop(
    db: AsyncSession,
    user_id: str,
    system_prompt: str,
    user_prompt: str,
    provider: Any,
    model: str,
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
    max_rounds: int = 3,
) -> tuple[str, list[dict[str, Any]]]:
    """章节生成工具循环：模型可调用 MCP 创作/查询工具，结果回填后继续写作。

    复用 agent_chat 模式：provider.generate(tools=...) → tool_calls → 执行工具
    → 历史（含 tool 结果）压回 prompt → 下一轮。最多 max_rounds 轮。
    创作工具（read_bible 等）直连并透传 user_id（按用户隔离，非 admin 视角）；
    其余工具经 _call_tool（系统 admin 视角）。返回 (最终正文, 工具调用日志)。
    """
    from types import SimpleNamespace

    from app.mcp.server import _call_tool, _openai_tools

    _CREATION_TOOLS = {
        "read_bible",
        "write_chapter",
        "update_character_state",
        "list_outline",
    }

    async def _run_tool(name: str, args: dict[str, Any]) -> str:
        from app.mcp import server as mcp_server

        if name in _CREATION_TOOLS:
            fn = getattr(mcp_server, name)
            result = await fn(**args, ctx=SimpleNamespace(user_id=user_id))
            if isinstance(result, dict) and "error" in result:
                return f"工具执行失败: {result['error']}"
            return json.dumps(result, ensure_ascii=False)[:2000]
        return await _call_tool(name, args)

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
    tool_log: list[dict[str, Any]] = []
    for _ in range(max_rounds):
        prompt = "\n\n".join(
            f"{m.get('role')}: {m.get('content')}"
            if m.get("content")
            else (
                f"{m.get('role')}: (调用工具 "
                f"{[tc.get('name') for tc in m.get('tool_calls') or []]})"
            )
            for m in messages
        )
        result = await provider.generate(
            prompt,
            model,
            system=system_prompt,
            tools=_openai_tools(),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        calls = result.tool_calls or []
        if not calls:
            return (result.content or "").strip(), tool_log
        for tc in calls:
            name = str(tc.get("name") or "")
            try:
                args = tc.get("arguments") or {}
                args = json.loads(args) if isinstance(args, str) else (args or {})
            except ValueError, TypeError:
                args = {}
            out = await _run_tool(name, args if isinstance(args, dict) else {})
            tool_log.append({"name": name, "summary": str(out)[:200]})
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tc],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tc.get("id") or ""),
                    "content": out,
                }
            )
    # 轮次耗尽：最后一次结果
    last = messages[-1].get("content") if messages else ""
    return str(last or "").strip(), tool_log


async def generate_chapter(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    chapter_id: str,
    *,
    model: str = "",
    max_tokens: int | None = None,
    temperature: float | None = None,
    instruction: str = "",
    tool_loop: bool = False,
) -> dict[str, Any]:
    """叙事模式：以角色扮演设定驱动作者视角，生成第 N 章小说正文。

    tool_loop=True：允许模型调用 MCP 工具（技能/创作工具），结果回填后续写。
    """
    project = await get_project(db, user_id, project_id)
    chapter = await get_chapter(db, user_id, chapter_id)
    if project is None or chapter is None:
        return {"error": "项目或章节不存在"}
    cards = await roleplay._load_cards(db, user_id, _load_json(project.character_asset_ids, []))
    if not cards:
        # 酒馆角色卡缺失时回退占位角色卡（story_characters 文本即虚拟卡）
        cards = await _placeholder_cards(db, user_id, project)
    if not cards:
        return {"error": "项目未关联角色卡，请先添加角色"}

    names = [c.get("name") or "角色" for _, c in cards]
    system_prompt, user_prompt, wb = await _build_chapter_prompt(
        db, user_id, project, chapter, cards, instruction
    )

    resolved = await resolve_text_provider(db, model)
    provider = roleplay.cast_text_provider(resolved.provider)
    tool_log: list[dict[str, Any]] = []
    try:
        if tool_loop:
            content, tool_log = await _chapter_tool_loop(
                db,
                user_id,
                system_prompt,
                user_prompt,
                provider,
                resolved.model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        else:
            result = await provider.generate(
                user_prompt,
                resolved.model,
                system=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = (result.content or "").strip()
    except Exception as exc:
        return {"error": f"生成失败：{str(exc)[:200]}"}
    if not content:
        return {"error": "模型未返回内容"}

    # 正则后处理（ai_output）
    scripts = await roleplay._load_regex_scripts(db, user_id)
    if scripts:
        content = roleplay._apply_regex(scripts, content, "ai_output", names)
    # 去除模型偶尔输出的章节标题前缀
    content = re.sub(rf"^第\s*{chapter.chapter_no}\s*章.*?\n", "", content, count=1).strip()

    await _snapshot_chapter(db, chapter, note="重新生成")
    chapter.content = content
    chapter.word_count = len(content)
    chapter.model = resolved.model
    chapter.status = "done"
    if tool_log:
        notes = _load_json(chapter.notes, {})
        notes["tool_calls"] = tool_log
        chapter.notes = json.dumps(notes, ensure_ascii=False)
    await db.commit()
    await db.refresh(chapter)
    return {
        "chapter_id": chapter.id,
        "content": content,
        "word_count": chapter.word_count,
        "model": resolved.model,
        "worldbook_hits": len(wb.activated),
        "tool_calls": tool_log,
        "status": "done",
    }


# ==== 剧本模式生成（群聊引擎） ====


async def generate_chapter_script(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    chapter_id: str,
    *,
    rounds: int = 6,
    model: str = "",
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """剧本模式：复用群聊引擎让角色轮流发言，拼装成对话流章节。"""
    project = await get_project(db, user_id, project_id)
    chapter = await get_chapter(db, user_id, chapter_id)
    if project is None or chapter is None:
        return {"error": "项目或章节不存在"}
    cards = await roleplay._load_cards(db, user_id, _load_json(project.character_asset_ids, []))
    if not cards:
        # 酒馆角色卡缺失时回退占位角色卡（story_characters 文本即虚拟卡）
        cards = await _placeholder_cards(db, user_id, project)
    if len(cards) < 1:
        return {"error": "项目未关联角色卡，请先添加角色"}
    if len(cards) < 2:
        return {"error": "剧本模式需要至少 2 个角色，请先在项目设置中添加角色"}

    scene = chapter.outline or chapter.title
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"场景：{scene}。角色们开始这场戏。"}
    ]
    resolved = await resolve_text_provider(db, model)
    provider = roleplay.cast_text_provider(resolved.provider)
    turns: list[str] = []
    for i in range(rounds):
        system_prompt, user_prompt, _wb, speaker = await roleplay._build_prompt(
            db,
            user_id,
            cards,
            messages,
            group=True,
            group_strategy="list",
            group_mode="swap",
            memory_summary=_project_summary(project),
        )
        try:
            result = await provider.generate(
                user_prompt,
                resolved.model,
                system=system_prompt,
                temperature=0.9 if i % 2 else 0.7,
                max_tokens=max_tokens or 400,
            )
        except Exception as exc:
            if i == 0:
                return {"error": f"生成失败：{str(exc)[:200]}"}
            break
        reply = (result.content or "").strip()
        reply, _mood = roleplay.extract_mood(reply)
        if not reply:
            continue
        # 去掉模型自带的角色名前缀（我们已用 speaker 标注）
        if not speaker:
            speaker = next((c.get("name") or "角色") for _, c in cards)
        # 去掉模型自带的角色名前缀（含「角色（头衔）」形式），避免重复标注
        reply = re.sub(rf"^{re.escape(speaker)}(（[^）]*）)?[：:]\s*", "", reply).strip()
        turns.append(f"{speaker}：{reply}")
        messages.append({"role": "assistant", "content": f"{speaker}：{reply}"})
        # 场景提示后需要角色回应：追加轻提示轮
        if i < rounds - 1:
            messages.append({"role": "user", "content": "（继续这场戏，轮到下一个角色发言。）"})
    if not turns:
        return {"error": "模型未返回任何台词"}

    content = (
        f"# 第 {chapter.chapter_no} 章《{chapter.title}》（剧本）\n\n"
        f"场景：{scene}\n\n" + "\n\n".join(turns)
    )
    await _snapshot_chapter(db, chapter, note="重新生成（剧本）")
    chapter.content = content
    chapter.word_count = len(content)
    chapter.model = resolved.model
    chapter.status = "done"
    await db.commit()
    await db.refresh(chapter)
    return {
        "chapter_id": chapter.id,
        "content": content,
        "word_count": chapter.word_count,
        "model": resolved.model,
        "turns": len(turns),
        "status": "done",
    }


# ==== 大纲生成 ====


async def generate_outline(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    *,
    chapters: int = _OUTLINE_CHAPTERS,
    model: str = "",
) -> dict[str, Any]:
    """根据梗概 + 角色设定生成全章大纲，批量创建章节行（status=outline）。"""
    project = await get_project(db, user_id, project_id)
    if project is None:
        return {"error": "项目不存在"}
    cards = await roleplay._load_cards(db, user_id, _load_json(project.character_asset_ids, []))
    names = [c.get("name") or "角色" for _, c in cards]
    lore_entries = await roleplay._load_lore_entries(db, user_id, names, project.id)
    wb = match_worldbook(lore_entries, [project.synopsis], max_depth=6)
    bible = await _bible_text(db, user_id, project, cards)
    wb_text = "\n".join(f"- {t}" for t in wb.before + wb.after)

    system_prompt = (
        "【创作任务】你是小说策划编辑。根据故事梗概、角色设定与世界观，"
        f"为《{project.title}》规划共 {chapters} 章的故事大纲。\n"
        f"【故事梗概】\n{project.synopsis}\n"
        f"【世界观】\n{wb_text}\n"
        f"【角色设定】\n{bible}\n"
    )
    # 项目配置的知识库文档：检索相关片段注入（本格推理规范等）
    knowledge_refs = await _knowledge_refs(db, user_id, project, project.synopsis)
    if knowledge_refs:
        system_prompt += knowledge_refs + "\n"
    system_prompt += (
        '【输出格式】只输出 JSON 数组，每项 {"title": "章节标题", "outline": '
        '"本章剧情要点（2-3 句）"}，'
        "不要输出其他文字。"
    )
    resolved = await resolve_text_provider(db, model)
    provider = roleplay.cast_text_provider(resolved.provider)
    try:
        result = await provider.generate(system_prompt, resolved.model, max_tokens=2048)
    except Exception as exc:
        return {"error": f"生成失败：{str(exc)[:200]}"}
    raw = (result.content or "").strip()
    parsed = _parse_outline_json(raw, chapters)
    if not parsed:
        parsed = [{"title": f"第 {i} 章", "outline": ""} for i in range(1, chapters + 1)]
    created: list[dict[str, Any]] = []
    for i, item in enumerate(parsed, start=1):
        c = await create_chapter(
            db,
            user_id,
            project_id,
            chapter_no=i,
            title=str(item.get("title") or f"第 {i} 章"),
            outline=str(item.get("outline") or ""),
        )
        created.append(_chapter_dict(c))
    await update_project(db, user_id, project_id, {"status": "ongoing"})
    return {"project_id": project_id, "chapters": created}


def _parse_outline_json(raw: str, chapters: int) -> list[dict[str, Any]]:
    """宽容解析模型输出：取第一个 [ ... ] 数组；失败返回 []。"""
    m = re.search(r"\[[\s\S]*\]", raw)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError, TypeError:
        return []
    if not isinstance(data, list):
        return []
    items: list[dict[str, Any]] = []
    for it in data[:chapters]:
        if isinstance(it, dict):
            items.append(
                {
                    "title": str(it.get("title") or ""),
                    "outline": str(it.get("outline") or ""),
                }
            )
    return items


# ==== 修订 ====


async def _snapshot_chapter(db: AsyncSession, chapter: Any, note: str = "") -> None:
    """修订/重新生成覆盖前保存旧内容快照（仅当已有正文）。"""
    if not (chapter.content or "").strip():
        return
    from app.models.story_chapter_version import StoryChapterVersion

    db.add(
        StoryChapterVersion(
            chapter_id=str(chapter.id),
            user_id=str(chapter.user_id),
            content=str(chapter.content),
            word_count=len(chapter.content or ""),
            note=(note or "")[:400],
        )
    )


async def list_chapter_versions(
    db: AsyncSession, user_id: str, chapter_id: str
) -> list[dict[str, Any]]:
    """章节版本列表（新→旧）。"""
    from app.models.story_chapter_version import StoryChapterVersion

    rows = (
        (
            await db.execute(
                select(StoryChapterVersion)
                .where(
                    StoryChapterVersion.chapter_id == chapter_id,
                    StoryChapterVersion.user_id == user_id,
                )
                .order_by(StoryChapterVersion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": v.id,
            "word_count": v.word_count,
            "note": v.note,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in rows
    ]


async def restore_chapter_version(
    db: AsyncSession, user_id: str, chapter_id: str, version_id: str
) -> dict[str, Any]:
    """还原到指定版本：当前内容先快照，再覆盖。"""
    from app.models.story_chapter_version import StoryChapterVersion

    chapter = await get_chapter(db, user_id, chapter_id)
    if chapter is None:
        return {"error": "章节不存在"}
    version = (
        await db.execute(
            select(StoryChapterVersion).where(
                StoryChapterVersion.id == version_id,
                StoryChapterVersion.chapter_id == chapter_id,
                StoryChapterVersion.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if version is None:
        return {"error": "版本不存在"}
    await _snapshot_chapter(db, chapter, note="还原前快照")
    chapter.content = version.content
    chapter.word_count = len(version.content or "")
    chapter.status = "done"
    await db.commit()
    return {"ok": True, "word_count": chapter.word_count}


async def revise_chapter(
    db: AsyncSession,
    user_id: str,
    chapter_id: str,
    instruction: str,
    *,
    model: str = "",
) -> dict[str, Any]:
    """按指令修订章节正文。"""
    chapter = await get_chapter(db, user_id, chapter_id)
    if chapter is None:
        return {"error": "章节不存在"}
    if not instruction.strip():
        return {"error": "请提供修订指令"}
    project = await get_project(db, user_id, chapter.project_id)
    original = str(chapter.content or "")
    # 创作罗盘（与章节生成一致）：修订同样守住全书承诺
    compass = ""
    if project is not None:
        compass_cfg = _load_json(project.settings, {}).get("compass") or {}
        intent = str(compass_cfg.get("intent") or "").strip()
        focus = str(compass_cfg.get("focus") or "").strip()
        if intent or focus:
            compass = "\n".join(
                [
                    f"【全书承诺】（不可违反）\n{intent}" if intent else "",
                    f"【当前阶段目标】\n{focus}" if focus else "",
                ]
            ).strip()
    system_prompt = (
        f"你是小说《{project.title if project else ''}》的执笔作者。按指令修订指定章节正文。\n"
        "要求：保持整体情节与风格不变，只按指令调整；只输出修订后的完整正文，不要解释。"
    )
    if compass:
        system_prompt += f"\n\n{compass}"
    style_block = writing_style_block(project)  # type: ignore[arg-type]
    if style_block:
        system_prompt += f"\n\n{style_block}"
    user_prompt = f"【修订指令】\n{instruction}\n\n【原文】\n{original}\n\n请输出修订后的正文："
    resolved = await resolve_text_provider(db, model)
    provider = roleplay.cast_text_provider(resolved.provider)
    try:
        result = await provider.generate(user_prompt, resolved.model, system=system_prompt)
    except Exception as exc:
        return {"error": f"生成失败：{str(exc)[:200]}"}
    content = (result.content or "").strip()
    if not content:
        return {"error": "模型未返回内容"}
    await _snapshot_chapter(db, chapter, note=f"修订：{instruction[:120]}")
    chapter.content = content
    chapter.word_count = len(content)
    chapter.status = "done"
    await db.commit()
    await db.refresh(chapter)
    return {"chapter_id": chapter.id, "content": content, "word_count": chapter.word_count}


# ==== 导出 ====


async def export_project(
    db: AsyncSession, user_id: str, project_id: str, fmt: str = "markdown"
) -> dict[str, Any]:
    """导出整本：markdown（书名+梗概+逐章正文）/ jsonl（结构化）/ epub（电子书）。"""
    project = await get_project(db, user_id, project_id)
    if project is None:
        return {"error": "项目不存在"}
    chapters = await list_chapters(db, user_id, project_id)
    if fmt == "epub":
        return {
            "filename": f"{project.title}.epub",
            "content": _build_epub(project, chapters),
            "binary": True,
        }
    if fmt == "jsonl":
        lines = [
            json.dumps(
                {
                    "type": "story",
                    "title": project.title,
                    "genre": project.genre,
                    "synopsis": project.synopsis,
                },
                ensure_ascii=False,
            )
        ]
        for c in chapters:
            lines.append(
                json.dumps(
                    {
                        "type": "chapter",
                        "chapter_no": c["chapter_no"],
                        "title": c["title"],
                        "outline": c["outline"],
                        "content": c["content"],
                        "status": c["status"],
                    },
                    ensure_ascii=False,
                )
            )
        return {"filename": f"{project.title}.jsonl", "content": "\n".join(lines)}
    parts = [f"# {project.title}", ""]
    if project.genre:
        parts.append(f"类型：{project.genre}")
    if project.synopsis:
        parts += ["", "## 梗概", "", project.synopsis]
    for c in chapters:
        parts += ["", f"## 第 {c['chapter_no']} 章 {c['title']}", ""]
        parts.append(c["content"] or "(未生成)")
    return {"filename": f"{project.title}.md", "content": "\n".join(parts)}


def _build_epub(project: StoryProject, chapters: list[dict[str, Any]]) -> bytes:
    """手写 EPUB 2.0（zipfile，无第三方依赖）：mimetype + container + opf + xhtml。"""
    import io
    import zipfile

    def esc(text: str) -> str:
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    title = project.title or "未命名作品"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # mimetype 必须无压缩且是第一个文件（EPUB 规范）
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        manifest = [
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
            '<item id="title-page" href="title.xhtml" media-type="application/xhtml+xml"/>',
        ]
        spine = ['<itemref idref="title-page"/>']
        for c in chapters:
            cid = f"ch{c['chapter_no']}"
            manifest.append(
                f'<item id="{cid}" href="ch{c["chapter_no"]}.xhtml" '
                'media-type="application/xhtml+xml"/>'
            )
            spine.append(f'<itemref idref="{cid}"/>')
        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" '
            'version="2.0" unique-identifier="bookid">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{esc(title)}</dc:title>"
            f"<dc:language>zh-CN</dc:language>"
            f"<dc:creator>AIGC Studio</dc:creator>"
            f"<dc:description>{esc(project.synopsis)}</dc:description>"
            "</metadata>"
            f"<manifest>{''.join(manifest)}</manifest>"
            f'<spine toc="ncx">{"".join(spine)}</spine>'
            "</package>",
        )
        # toc.ncx（章节导航）
        navpoints = "".join(
            f'<navPoint id="np{c["chapter_no"]}" playOrder="{c["chapter_no"]}">'
            f"<navLabel><text>{esc(c['title'])}</text></navLabel>"
            f'<content src="ch{c["chapter_no"]}.xhtml"/></navPoint>'
            for c in chapters
        )
        zf.writestr(
            "OEBPS/toc.ncx",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            f'<head><meta name="dtb:uid" content="aigc-{project.id}"/></head>'
            f"<docTitle><text>{esc(title)}</text></docTitle>"
            f"<navMap>{navpoints}</navMap></ncx>",
        )
        # 书名页
        zf.writestr(
            "OEBPS/title.xhtml",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>'
            f"{esc(title)}</title></head><body>"
            f"<h1>{esc(title)}</h1>"
            f"<p>{esc(project.genre)}</p>"
            f"<p>{esc(project.synopsis)}</p></body></html>",
        )
        # 章节
        for c in chapters:
            body = esc(c["content"] or "(未生成)").replace("\n", "<br/>")
            zf.writestr(
                f"OEBPS/ch{c['chapter_no']}.xhtml",
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>'
                f"{esc(c['title'])}</title></head><body>"
                f"<h2>{esc(c['title'])}</h2><p>{body}</p></body></html>",
            )
    return buf.getvalue()


# ===== 写法特征池（AI-Novel 写法引擎借鉴）：从好章节提取写法特征，注入后续生成 =====

_WRITING_STYLE_PROMPT = """你是资深文学编辑。从以下章节正文中提炼「写法特征」（作者是怎么写的），
供后续章节模仿。规则：
- 提取 3-5 条，每条 = 特征名（4-8 字）+ 一句话说明（怎么写的，含一个原文示例片段，10 字内）
- 只提炼「写法层面」：句式节奏 / 白描或修辞习惯 / 对话写法 / 视角与留白 / 用词偏好
- 不要提炼剧情内容（剧情是内容不是写法）
输出 JSON（不要任何多余文字）：{{"features": [{{"name": "白描短句", "desc": "三五个字的动
作短句，不解释情绪，如『他愣了愣』", "en

a
b
l
e
d
"
: true}}]}}

章节正文：
{content}"""


async def extract_writing_style(
    db: AsyncSession, user_id: str, project_id: str, chapter_id: str
) -> dict[str, Any]:
    """从指定章节提取写法特征（存项目 settings.writing_style）。"""
    project = await get_project(db, user_id, project_id)
    if project is None:
        return {"error": "项目不存在"}
    chapter = await get_chapter(db, user_id, chapter_id)
    if chapter is None:
        return {"error": "章节不存在"}
    content = str(chapter.content or "").strip()
    if len(content) < 200:
        return {"error": "章节正文太短（<200 字），先完成写作再提取"}
    resolved = await resolve_text_provider(db, "")
    try:
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            _WRITING_STYLE_PROMPT.format(content=content[:5000]),
            resolved.model,
            temperature=0.3,
        )
        from app.services.text_utils import extract_json, result_text

        data = extract_json(result_text(result))
        features = [f for f in (data.get("features") or []) if isinstance(f, dict)]
        if not features:
            return {"error": "未能提炼出写法特征"}
        # 限制条数与字段长度
        cleaned = []
        for f in features[:5]:
            cleaned.append(
                {
                    "name": str(f.get("name") or "特征")[:12],
                    "desc": str(f.get("desc") or "")[:120],
                    "enabled": bool(f.get("enabled", True)),
                }
            )
        settings = _load_json(project.settings, {})
        settings["writing_style"] = cleaned
        project.settings = json.dumps(settings, ensure_ascii=False)
        await db.commit()
        return {"ok": True, "features": cleaned}
    except Exception as exc:
        return {"error": f"提取失败：{str(exc)[:120]}"}


def writing_style_block(project: StoryProject) -> str:
    """写法特征池 → 注入文本（仅启用的特征；无则空串）。"""
    cfg = _load_json(project.settings, {}).get("writing_style") or []
    enabled = [f for f in cfg if isinstance(f, dict) and f.get("enabled")]
    if not enabled:
        return ""
    lines = [f"- {f.get('name', '特征')}：{f.get('desc', '')}" for f in enabled[:5]]
    return "【写作特征池】（本项目已确认的写法特征，本章必须延续这些写法）\n" + "\n".join(lines)
