"""创作工作台：主题 → AI 选角 → 剧本初稿 → 生成角色卡 → 自动建群（AI 导演工作室）。

流程：
1. plan(theme)：AI 分析主题，产出角色方案（角色定位/性格/开场白）+ 群名建议
2. script(theme, plan)：按主题+角色阵容产出分幕剧本大纲（幕/场/冲突/对白提示）
3. setup(plan)：批量创建角色卡（asset + 结构化角色行）→ 自动建群 → 角色入群
4. 用户在群内分角色共创（复用现有群聊）
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.roleplay_character import RoleplayCharacter
from app.models.roleplay_chat import RoleplayChat
from app.services.group_service import create_group
from app.services.provider_resolver import resolve_text_provider
from app.services.sessions import create_chat as create_chat_row
from app.services.text_utils import result_text as _result_text

_PLAN_PROMPT = """你是影视/小说项目的选角导演。根据创作主题，规划一个多人共创项目。

严格输出 JSON（不要任何多余文字）：
{{
  "group_name": "项目/群名（2-8 字，有辨识度）",
  "genre": "类型（如：本格推理 / 都市情感 / 科幻冒险）",
  "logline": "一句话故事梗概（30-60 字）",
  "characters": [
    {{
      "name": "角色名（2-4 字，好记）",
      "role": "定位（如：主角/侦探/嫌疑人/反派）",
      "description": "人物小传（50-100 字：身份/背景/性格矛盾点）",
      "personality": "性格关键词与说话风格（20-40 字）",
      "first_mes": "角色开场白（1-2 句，有辨识度，直接进入情境）",
      "source": "new 或 existing（复用角色池中的角色填 existing）",
      "asset_id": "source=existing 时必填（角色池中的 asset_id）；new 时省略"
    }}
  ]
}}

要求：
- 角色 3-6 个，定位互补（主角 + 对手 + 帮手/关系人），覆盖故事推进所需
- 每个角色适合真人扮演或 AI 扮演，定位清晰
- 主题：{theme}
- 若提供【主题相关资料】，必须优先基于资料设定角色（世界观/人物/事件以资料为准）
- 若提供【已有角色池】：人设合适的角色**优先复用**（source=existing + 其 asset_id），不要为已有角色造重复卡；确实缺的定位才新建（source=new）"""


# 主题相关资料（知识库检索命中时填充，未命中为空）
_THEME_MATERIALS_LABEL = """

【主题相关资料】（来自用户知识库，选角必须参考）
{materials}"""


# 已有角色池（主题相关检索命中时填充；AI 可直接引用 asset_id 复用）
_CHARACTER_POOL_LABEL = """

【已有角色池】（与主题相关的可复用演员；人设合适的直接引用，别新建重复卡）
{pool}"""


_SCRIPT_PROMPT = """你是资深编剧 + 剧作统筹。根据创作主题与角色阵容，产出剧本初稿的分幕大纲。
严格输出 JSON（不要任何多余文字）：

{{
  "title": "剧名（2-8 字，有记忆点）",
  "genre": "类型（与主题一致）",
  "logline": "一句话故事梗概（30-60 字）",
  "acts": [
    {{
      "act_no": 1,
      "act_title": "幕题（2-4 字，点出本幕核心）",
      "act_summary": "本幕剧情概览（60-100 字）",
      "scenes": [
        {{
          "scene_no": 1,
          "location": "场景（地点+时间，如：深夜食堂·店内·雨夜）",
          "characters": "出场角色（用角色名，逗号分隔）",
          "beat": "本场节拍（40-80 字：发生什么/冲突/转折，禁止流水账）",
          "dialogue_hint": "关键台词提示（1-2 句，贴合角色性格，可直接演）"
        }}
      ]
    }}
  ],
  "finale_hint": "结局走向提示（40-60 字）"
}}

要求：
- 共 3 幕（起→承转→合），每幕 2-4 场，全剧 6-10 场
- 每场必须有明确的戏剧冲突或信息转折；伏笔要在后文回收
- 台词节拍必须贴合角色方案中的性格与说话风格
- 主题：{theme}

角色阵容：
{cast}"""


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"error": "AI 输出解析失败", "raw": text[:500]}


async def _retrieve_theme_materials(
    db: AsyncSession, user_id: str, theme: str, limit: int = 3
) -> str:
    """按主题检索知识库文档（公共模块，圆桌/选角共用）。"""
    from app.services.knowledge_materials import retrieve_theme_materials

    return await retrieve_theme_materials(db, user_id, theme, limit=limit)


async def _retrieve_character_pool(
    db: AsyncSession,
    user_id: str,
    theme: str,
    limit: int = 6,
    min_score: int = 2,
) -> list[dict[str, Any]]:
    """按主题检索已有角色卡（本人 + 共享），供 AI 选角直接复用。

    与知识库检索同引擎：角色描述/性格/场景分块打分。
    无命中返回空列表——不阻塞。
    """
    from app.services.knowledge_retrieval import retrieve

    rows = (
        (
            await db.execute(
                select(RoleplayCharacter)
                .where(
                    or_(
                        RoleplayCharacter.user_id == user_id,
                        RoleplayCharacter.is_shared.is_(True),
                    )
                )
                .limit(300)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    chunks = [
        (
            r.asset_id,
            str(r.name or ""),
            f"{r.description or ''} {r.personality or ''} {r.scenario or ''}",
        )
        for r in rows
    ]
    hits = retrieve(chunks, theme, top_k=limit, min_score=min_score)
    if not hits:
        return []
    by_id = {r.asset_id: r for r in rows}
    pool: list[dict[str, Any]] = []
    for asset_id, _title, _text, score in hits:
        row = by_id.get(asset_id)
        if row is None:
            continue
        pool.append(
            {
                "asset_id": asset_id,
                "name": str(row.name or ""),
                "personality": str(row.personality or "")[:120],
                "description": str(row.description or "")[:120],
                "score": score,
            }
        )
    return pool


async def plan_project(db: AsyncSession, theme: str, user_id: str | None = None) -> dict[str, Any]:
    """主题 → 角色方案。user_id 提供时先检索其知识库资料 + 已有角色池，
    选角参考（无命中不阻塞）。"""
    materials = ""
    pool: list[dict[str, Any]] = []
    if user_id:
        materials = await _retrieve_theme_materials(db, user_id, theme)
        pool = await _retrieve_character_pool(db, user_id, theme)
    extras: list[str] = []
    if materials:
        extras.append(_THEME_MATERIALS_LABEL.format(materials=materials))
    if pool:
        pool_lines = "\n".join(
            f"- asset_id: {p['asset_id']} | {p['name']}（{p['personality']}）｜{p['description']}"
            for p in pool
        )
        extras.append(_CHARACTER_POOL_LABEL.format(pool=pool_lines))
    if extras:
        theme = theme + "".join(extras)
    prompt = _PLAN_PROMPT.format(theme=theme)
    resolved = await resolve_text_provider(db, "")
    result = await resolved.provider.generate(prompt, resolved.model)  # type: ignore[attr-defined]
    if isinstance(result, dict):
        text = str(result.get("text") or result.get("content") or "")
    elif hasattr(result, "content"):
        text = str(result.content)
    else:
        text = str(result)
    data = _extract_json(text)
    data["provider"] = resolved.model
    if materials:
        data["materials_hits"] = True
    if pool:
        data["pool_hits"] = len(pool)
        data["pool"] = pool
    return data


async def _script_once(
    db: AsyncSession,
    *,
    theme: str,
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """单次分幕大纲生成（variants 多版本复用的内部实现）。"""
    characters = (plan or {}).get("characters") or []
    if isinstance(characters, list) and characters:
        cast_lines = "\n".join(
            f"- {c.get('name')}（{c.get('role')}）：性格/说话风格：{str(c.get('personality') or c.get('description') or '')[:80]}"
            for c in characters
        )
    else:
        cast_lines = "（无固定角色阵容，可自创角色，但需在每场 characters 中给出定位）"
    prompt = _SCRIPT_PROMPT.format(theme=theme, cast=cast_lines)
    resolved = await resolve_text_provider(db, "")
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        prompt, resolved.model, temperature=0.9
    )
    if isinstance(result, dict):
        text = str(result.get("text") or result.get("content") or "")
    elif hasattr(result, "content"):
        text = str(result.content)
    else:
        text = str(result)
    data = _extract_json(text)
    data["provider"] = resolved.model
    return data


_REVIEW_PROMPT = """你是制片人视角的剧本评审。评审以下剧本大纲，严格输出 JSON（不要任何多余文字）：

{{
  "score": "0-10 的整数（题材完成度/结构/冲突强度/可行性综合分）",
  "strengths": ["亮点1", "亮点2", "亮点3（2-3 条，具体到幕/场）"],
  "weaknesses": ["弱点1", "弱点2", "弱点3（2-4 条，具体到结构/冲突/角色弧）"],
  "suggestions": ["具体改进建议1", "建议2（2-4 条，可直接执行的修改方向）"]
}}

要求：评审要专业具体，引用幕/场/角色名，不写套话。

主题：{theme}

剧本大纲：
{script}"""


async def review_project(
    db: AsyncSession,
    *,
    theme: str,
    plan: dict[str, Any] | None = None,
    script: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """剧本大纲评审：评分/亮点/弱点/改进建议。"""
    script_json = json.dumps(script or {}, ensure_ascii=False)[:6000]
    prompt = _REVIEW_PROMPT.format(theme=theme, script=script_json)
    resolved = await resolve_text_provider(db, "")
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        prompt, resolved.model, temperature=0.7
    )
    data = _extract_json(_result_text(result))
    data["provider"] = resolved.model
    return data


async def script_project(
    db: AsyncSession,
    *,
    theme: str,
    plan: dict[str, Any] | None = None,
    variants: int = 1,
) -> dict[str, Any]:
    """主题（+角色方案）→ 分幕剧本大纲。variants>1 时并行生成多版对比。"""
    if variants > 1:
        import asyncio

        n = min(variants, 3)
        results = await asyncio.gather(
            *[_script_once(db, theme=theme, plan=plan) for _ in range(n)]
        )
        return {"variants": list(results)}
    return await _script_once(db, theme=theme, plan=plan)


_PUBLISH_PROMPT = """你是场记 + 编剧。把群里共创的演出记录整理成一份完整剧本（可直接存档/连载）：

格式要求：
- 按剧情自然分幕分场：**第X幕** / **第X场·地点·时间**
- 每场：场景描述（2-3 句）+ 【角色名】对白 + 动作/转场提示
- 忠实于已演内容：可润色对白、补全动作与转场，不得编造未演情节
- 800-1500 字，直接输出剧本正文，不要任何说明文字

群演出记录：
{transcript}"""


def _chat_transcript(chat: RoleplayChat) -> str:
    """群消息 → 演出记录文本（标记发言者，截断过长历史）。"""
    from app.services import sessions as _sessions

    msgs = _sessions.chat_messages(chat)[-60:]
    lines: list[str] = []
    for m in msgs:
        role = m.get("role", "")
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"（演出/指令）{content}")
        else:
            lines.append(f"（AI 演出）{content}")
    return "\n".join(lines) if lines else "（群内暂无演出记录）"


async def publish_project(
    db: AsyncSession,
    *,
    user_id: str,
    chat_id: str,
    title: str | None = None,
) -> dict[str, Any]:
    """群演出 → 完整剧本 → 存入创作工作室（story 项目 + 首章）。

    返回 {project_id, chapter_id, project_title}；群为空/无归属返回 error。
    """
    from app.services import sessions as _sessions
    from app.services.story_forge import create_chapter, create_project

    chat = await _sessions.get_chat(db, user_id, chat_id)
    if chat is None:
        return {"error": "群不存在或无权访问"}
    transcript = _chat_transcript(chat)
    if "暂无演出记录" in transcript:
        return {"error": "群里还没有演出内容，先演几场再来存档吧"}

    resolved = await resolve_text_provider(db, "")
    provider = resolved.provider
    try:
        result = await provider.generate(  # type: ignore[attr-defined]
            _PUBLISH_PROMPT.format(transcript=transcript),
            resolved.model,
            temperature=0.75,
        )
    except Exception as exc:
        return {"error": f"剧本整理失败：{str(exc)[:200]}"}
    if isinstance(result, dict):
        script_text = str(result.get("text") or result.get("content") or "")
    elif hasattr(result, "content"):
        script_text = str(result.content)
    else:
        script_text = str(result)
    if not script_text.strip():
        return {"error": "剧本整理为空，请重试"}

    try:
        char_ids = json.loads(chat.character_asset_ids) if chat.character_asset_ids else []
    except Exception:
        char_ids = []
    project = await create_project(
        db,
        user_id,
        title=(title or chat.title or "群演作品")[:200],
        synopsis=str(chat.title or "")[:500],
        genre="群演剧本",
        character_asset_ids=char_ids if isinstance(char_ids, list) else [],
    )
    chapter = await create_chapter(db, user_id, project.id, title="群演完整剧本", outline="")
    await update_chapter_content(db, user_id, chapter.id, script_text)
    return {
        "project_id": project.id,
        "chapter_id": chapter.id,
        "project_title": project.title,
    }


async def update_chapter_content(
    db: AsyncSession, user_id: str, chapter_id: str, content: str
) -> None:
    """写入章节正文（story_forge.update_chapter 同款字段的轻量直连）。"""
    from sqlalchemy import update as sa_update

    from app.models.story_chapter import StoryChapter

    await db.execute(
        sa_update(StoryChapter)
        .where(
            StoryChapter.id == chapter_id,
            StoryChapter.user_id == user_id,
        )
        .values(content=content)
    )
    await db.commit()


async def setup_project(
    db: AsyncSession,
    *,
    owner_id: str,
    theme: str,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建角色卡 + 建群 + 角色入群。plan 为空时先用 AI 生成。

    去重复用：角色名与本人已有角色卡（或共享角色卡）同名时直接复用，
    不重复创建——「下一次创作先查已有角色，相同的直接用」。
    """
    if plan is None:
        plan = await plan_project(db, theme, user_id=owner_id)
    characters = plan.get("characters") or []
    if not isinstance(characters, list) or not characters:
        return {"error": "角色方案无效，请重新规划"}

    # 一次性批量查已有角色（本人 + 共享）：AI 引用的 asset_id 优先，未引用则按名查重
    ref_ids = [str(c.get("asset_id") or "").strip() for c in characters[:8] if c.get("asset_id")]
    names = [str(c.get("name") or "").strip()[:100] for c in characters[:8]]
    existing_rows = (
        (
            await db.execute(
                select(RoleplayCharacter).where(
                    or_(
                        RoleplayCharacter.asset_id.in_([i for i in ref_ids if i]),
                        RoleplayCharacter.name.in_([n for n in names if n]),
                    ),
                    or_(
                        RoleplayCharacter.user_id == owner_id,
                        RoleplayCharacter.is_shared.is_(True),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    by_asset: dict[str, RoleplayCharacter] = {r.asset_id: r for r in existing_rows}
    by_name: dict[str, RoleplayCharacter] = {r.name: r for r in existing_rows}

    created: list[dict[str, Any]] = []
    reused_count = 0
    char_ids: list[str] = []
    for c in characters[:8]:
        name = str(c.get("name") or f"角色{len(created) + 1}")[:100]
        existing: RoleplayCharacter | None = None
        # 1) AI 引用已有角色（asset_id 命中且归属本人/共享）→ 直接复用
        ref_asset = str(c.get("asset_id") or "").strip()
        if ref_asset:
            existing = by_asset.get(ref_asset)
        # 2) 未引用/引用失效 → 同名复用兜底
        if existing is None:
            existing = by_name.get(name)
        if existing is not None:
            # 复用已有角色卡：不新建 asset/角色行，直接入群
            char_ids.append(existing.asset_id)
            reused_count += 1
            created.append(
                {
                    "asset_id": existing.asset_id,
                    "name": name,
                    "role": str(c.get("role") or ""),
                    "personality": str(existing.personality or "")[:200],
                    "reused": True,
                }
            )
            continue
        asset_id = str(uuid.uuid4())
        asset = Asset(
            id=asset_id,
            user_id=owner_id,
            filename=f"character-{asset_id[:8]}.png",
            storage_key="",
            storage_backend="local",
            mime_type="image/png",
            size_bytes=0,
        )
        db.add(asset)
        db.add(
            RoleplayCharacter(
                asset_id=asset_id,
                user_id=owner_id,
                name=name,
                description=str(c.get("description") or "")[:4000],
                personality=str(c.get("personality") or "")[:2000],
                scenario=str(c.get("scenario") or "")[:2000],
                first_mes=str(c.get("first_mes") or f"（{name}登场）")[:2000],
            )
        )
        char_ids.append(asset_id)
        created.append(
            {
                "asset_id": asset_id,
                "name": name,
                "role": str(c.get("role") or ""),
                "personality": str(c.get("personality") or "")[:200],
                "reused": False,
            }
        )
    await db.flush()

    # 建群（is_room 会话 + 群记录 + 群主入群）
    group_name = str(plan.get("group_name") or theme)[:100]
    chat = await create_chat_row(
        db,
        owner_id,
        title=group_name,
        character_asset_ids=char_ids,
        group=len(char_ids) > 1,
        is_room=True,
    )
    await create_group(
        db,
        owner_id=owner_id,
        chat_id=chat.id,
        name=group_name,
        description=str(plan.get("logline") or "")[:500],
    )
    await db.commit()
    await db.refresh(chat)
    return {
        "chat_id": chat.id,
        "group_name": group_name,
        "genre": plan.get("genre", ""),
        "logline": plan.get("logline", ""),
        "characters": created,
        "reused_count": reused_count,
    }
