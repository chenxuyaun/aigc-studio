"""角色扮演服务（SillyTavern 功能融入版）。

核心链路：角色卡（V2 全字段）→ 世界书引擎（constant/selective/位置/深度/概率）
→ 宏展开 → prompt 组装（system/history/示例/作者注/persona/群聊 APPEND）
→ provider（system + 采样参数）→ 情绪提取 → 正则后处理 → 会话落库。
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.regex_script import RegexScript
from app.models.roleplay_character import RoleplayCharacter
from app.models.roleplay_lore import RoleplayLoreEntry
from app.models.roleplay_persona import RoleplayPersona
from app.providers.base import TextProvider
from app.services import sessions
from app.services.character_card import parse_character_card
from app.services.macros import substitute as substitute_macros
from app.services.provider_resolver import resolve_text_provider
from app.services.worldbook import match_worldbook

# 保留后台任务引用，避免被 GC 回收
_memory_tasks: set[asyncio.Task[Any]] = set()


def _record_memory_turn(
    user_id: str, asset_id: str, chat_id: str,
    user_msg: str, assistant_msg: str,
) -> None:
    """L0 对话写入 MemoryCore gateway（fire-and-forget，失败静默不阻塞对话）。"""
    if not user_id or not asset_id or not chat_id:
        return
    from app.services.memory_client import memory_add_conversation

    async def _run() -> None:
        await memory_add_conversation(
            user_id, asset_id, chat_id,
            [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_msg},
            ],
        )

    task = asyncio.create_task(_run())
    _memory_tasks.add(task)
    task.add_done_callback(_memory_tasks.discard)

_HISTORY_LIMIT = 40
_MAX_RECENT_FOR_LORE = 6


def parse_character_png(data: bytes) -> dict[str, Any]:
    """解析 SillyTavern 角色卡 PNG（tEXt 块 chara/ccv3，V1/V2/V3 全兼容）。"""
    return parse_character_card(data)


async def list_characters(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    """素材库中的角色卡资产列表（filename 以 character- 开头）。"""
    rows = (
        await db.execute(
            select(Asset).where(
                Asset.user_id == user_id,
                Asset.filename.like("character-%"),
                Asset.mime_type == "image/png",
            )
        )
    ).scalars().all()
    return [
        {
            "asset_id": a.id,
            "filename": a.filename,
            "url": f"/api/v1/assets/{a.id}/content",
            "created_at": str(a.created_at) if a.created_at else "",
        }
        for a in rows
    ]


# ==== 情绪与好感度（保留既有系统） ====

_MOOD_TAG_RE = re.compile(r"\[情绪[:：]\s*([^\]]+)\]")


def extract_mood(reply: str) -> tuple[str, str]:
    """从回复中提取情绪标签（[情绪:开心]），并移除标签保留正文。"""
    m = _MOOD_TAG_RE.search(reply)
    if not m:
        return reply.strip(), ""
    mood = m.group(1).strip()
    clean = _MOOD_TAG_RE.sub("", reply).strip()
    return clean, mood


def _mood_delta(mood: str) -> int:
    """情绪 → 好感度变化（正面+1 负面-1 中性0）。"""
    positive = ("开心", "高兴", "兴奋", "愉快", "喜欢", "友好", "温柔", "害羞", "感动")
    negative = ("生气", "愤怒", "伤心", "难过", "冷漠", "厌恶", "失望", "害怕")
    if any(k in mood for k in positive):
        return 1
    if any(k in mood for k in negative):
        return -1
    return 0


# ==== 角色卡加载 ====

def _card_to_json(card: dict[str, Any]) -> dict[str, Any]:
    """扁平卡字段 → roleplay_characters 行字段（JSON 列序列化）。"""
    return {
        "name": str(card.get("name") or ""),
        "description": str(card.get("description") or ""),
        "personality": str(card.get("personality") or ""),
        "scenario": str(card.get("scenario") or ""),
        "first_mes": str(card.get("first_mes") or ""),
        "mes_example": str(card.get("mes_example") or ""),
        "alternate_greetings": json.dumps(
            card.get("alternate_greetings") or [], ensure_ascii=False
        ),
        "system_prompt": str(card.get("system_prompt") or ""),
        "post_history_instructions": str(card.get("post_history_instructions") or ""),
        "creator_notes": str(card.get("creator_notes") or ""),
        "tags": json.dumps(card.get("tags") or [], ensure_ascii=False),
        "character_book": json.dumps(card.get("character_book") or {}, ensure_ascii=False),
        "talkativeness": float(card.get("talkativeness") or 0.5),
        "depth_prompt": json.dumps(card.get("depth_prompt") or {}, ensure_ascii=False),
        "settings": json.dumps(
            {k: card.get(k) for k in ("creator", "character_version") if card.get(k)},
            ensure_ascii=False,
        ),
    }


async def _sync_character_row(
    db: AsyncSession, user_id: str, asset_id: str, card: dict[str, Any]
) -> None:
    """角色卡懒同步：解析结果写入 roleplay_characters（供详情/编辑读取）。"""
    row = await db.get(RoleplayCharacter, asset_id)
    fields = _card_to_json(card)
    if row is None:
        db.add(RoleplayCharacter(asset_id=asset_id, user_id=user_id, **fields))
    else:
        for k, v in fields.items():
            setattr(row, k, v)


async def _load_cards(
    db: AsyncSession, user_id: str, character_asset_ids: list[str]
) -> list[tuple[str, dict[str, Any]]]:
    """加载多张角色卡（asset_id, 全字段 card dict）列表；失败项跳过。"""
    from app.storage import get_storage

    cards: list[tuple[str, dict[str, Any]]] = []
    for aid in character_asset_ids:
        asset = (
            await db.execute(
                select(Asset).where(Asset.id == aid, Asset.user_id == user_id)
            )
        ).scalar_one_or_none()
        if asset is None:
            continue
        # 优先读结构化行（已同步过的卡）
        row = await db.get(RoleplayCharacter, aid)
        if row is not None:
            card = {
                "name": row.name,
                "description": row.description,
                "personality": row.personality,
                "scenario": row.scenario,
                "first_mes": row.first_mes,
                "mes_example": row.mes_example,
                "alternate_greetings": _load_json(row.alternate_greetings, []),
                "system_prompt": row.system_prompt,
                "post_history_instructions": row.post_history_instructions,
                "creator_notes": row.creator_notes,
                "tags": _load_json(row.tags, []),
                "character_book": _load_json(row.character_book, {}),
                "talkativeness": row.talkativeness,
                "depth_prompt": _load_json(row.depth_prompt, {}),
            }
            cards.append((aid, card))
            continue
        store = get_storage(asset.storage_backend)
        data = await store.get(asset.storage_key)
        card = parse_character_png(data) if data else {}
        if card:
            await _sync_character_row(db, user_id, aid, card)
            cards.append((aid, card))
    return cards


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


# ==== 世界书（兼容层 + 新引擎入口） ====

async def _load_lore_entries(
    db: AsyncSession,
    user_id: str,
    character_names: list[str],
    project_id: str | None = None,
) -> list[RoleplayLoreEntry]:
    """加载命中的世界书条目：全局（character_name IS NULL）+ 当前角色绑定。

    project_id：创作项目作用域（Story Forge）——只取该项目条目；None 时取全局。
    """
    name_cond = (
        (
            RoleplayLoreEntry.character_name.is_(None)
            | RoleplayLoreEntry.character_name.in_(character_names)
        )
        if character_names
        else RoleplayLoreEntry.character_name.is_(None)
    )
    # 注意：is_() 只用于 None（MySQL 不允许 `column IS 'value'`）
    project_cond = (
        RoleplayLoreEntry.project_id.is_(None)
        if project_id is None
        else RoleplayLoreEntry.project_id == project_id
    )
    rows = (
        await db.execute(
            select(RoleplayLoreEntry).where(
                RoleplayLoreEntry.user_id == user_id,
                name_cond,
                project_cond,
            )
        )
    ).scalars().all()
    return list(rows)


async def _match_lore(
    db: AsyncSession, character_name: str, recent_messages: list[str]
) -> list[str]:
    """兼容层：按角色名 + 最近消息跑新引擎，返回 ['关键词：内容'] 旧格式。"""
    entries = await _load_lore_entries(db, "", [character_name])
    result = match_worldbook(entries, recent_messages, max_depth=_MAX_RECENT_FOR_LORE)
    return result.before + result.after


# ==== 快捷回复自动触发 ====

async def _load_auto_quick_replies(db: AsyncSession, user_id: str) -> list[Any]:
    from app.models.quick_reply import QuickReply

    rows = (
        await db.execute(
            select(QuickReply).where(
                QuickReply.user_id == user_id,
                QuickReply.auto.is_(True),
            )
        )
    ).scalars().all()
    return list(rows)


# ==== 正则脚本 ====

async def _load_regex_scripts(db: AsyncSession, user_id: str) -> list[RegexScript]:
    rows = (
        await db.execute(
            select(RegexScript).where(
                RegexScript.user_id == user_id, RegexScript.enabled.is_(True)
            )
        )
    ).scalars().all()
    return list(rows)


def _apply_regex(
    scripts: list[RegexScript], text: str, placement: str, character_names: list[str]
) -> str:
    """应用正则脚本（user_input 发送前 / ai_output 展示前）。"""
    out = text
    for s in scripts:
        if s.placement != placement:
            continue
        if s.scope == "character" and s.character_name not in character_names:
            continue
        try:
            out = re.sub(s.pattern, s.replacement, out)
        except re.error:
            continue
    return out


# ==== prompt 组装 ====

def _macro_context(
    cards: list[tuple[str, dict[str, Any]]],
    user_name: str,
    messages: list[dict[str, Any]],
    current_input: str = "",
) -> dict[str, Any]:
    last_user = next(
        (str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    last_msg = str(messages[-1].get("content") or "") if messages else ""
    names = [c.get("name") or "角色" for _, c in cards]
    return {
        "user": user_name,
        "char": cards[0][1] if cards else {},
        "group": "、".join(names),
        "input": current_input,
        "last_message": last_msg,
        "last_user_message": last_user,
        "seed": "|".join(names) + "|" + str(len(messages)),
    }


def _greeting_candidates(card: dict[str, Any]) -> list[str]:
    """首轮开场白候选：first_mes + 备用开场白（去空）。"""
    greetings = [str(card.get("first_mes") or "")]
    alts = card.get("alternate_greetings") or []
    if isinstance(alts, list):
        greetings += [str(g) for g in alts if str(g).strip()]
    return [g for g in greetings if g.strip()]


def _format_history(
    messages: list[dict[str, Any]], names: list[str], limit: int = _HISTORY_LIMIT
) -> list[str]:
    """历史 → 提示行（用户消息标名，角色消息原样）。"""
    lines: list[str] = []
    for m in messages[-limit:]:
        content = str(m.get("content") or "")
        if not content:
            continue
        if m.get("role") == "user":
            lines.append(f"用户：{content}")
        else:
            lines.append(content)
    return lines


def _format_examples(card: dict[str, Any]) -> str:
    """mes_example → 示例对话文本（<START> 分块保留）。"""
    raw = str(card.get("mes_example") or "").strip()
    if not raw:
        return ""
    blocks = raw.split("<START>")
    parts: list[str] = []
    for b in blocks:
        b = b.strip()
        if b:
            parts.append(b)
    return "\n\n".join(parts)


async def _build_prompt(
    db: AsyncSession,
    user_id: str,
    cards: list[tuple[str, dict[str, Any]]],
    messages: list[dict[str, Any]],
    *,
    group: bool = False,
    persona: RoleplayPersona | None = None,
    note: dict[str, Any] | None = None,
    continue_mode: bool = False,
    group_strategy: str = "natural",
    group_mode: str = "append",
    memory_summary: str = "",
) -> tuple[str, str, list[str], str]:
    """组装 (system, user_prompt, worldbook_activated, speaker)。

    system = 世界书before + 角色卡（主提示/描述/性格/场景，群聊 APPEND 全员）
             + persona + 作者注 + 世界书after + 情绪要求
    user_prompt = 示例对话 + 历史（atDepth 条目按深度插入中部）+ 群聊 nudge + 续写指令
    continue_mode：以最后一条角色回复的末尾为续写起点（截断其前半，追加续写指令）。
    group_strategy：natural（模型自选）/ list（按序轮流）/ random（随机指定）。
    group_mode：append（全员卡片注入）/ swap（仅注入当前说话者，省上下文）。
    """
    user_name = persona.name if persona else "用户"
    ctx = _macro_context(cards, user_name, messages)
    names = [c.get("name") or "角色" for _, c in cards]
    recent_texts = [str(m.get("content") or "") for m in messages[-_MAX_RECENT_FOR_LORE:]]

    # 世界书引擎
    lore_entries = await _load_lore_entries(db, user_id, names)
    wb = match_worldbook(lore_entries, recent_texts, max_depth=_MAX_RECENT_FOR_LORE)
    wb_before = [substitute_macros(t, ctx) for t in wb.before]
    wb_after = [substitute_macros(t, ctx) for t in wb.after]

    parts: list[str] = []
    if memory_summary:
        parts.append(f"【记忆摘要（此前对话的要点，保持连贯）】\n{memory_summary}")

    # 多层记忆注入（原著档案 + L3 画像 + L2 场景导航 → system 稳定部分；
    # L1 原子 + 原著事实检索 → user 动态部分，见下方 user_parts 开头）
    memory_system_extra = ""
    memory_user_extra = ""
    if not group or len(cards) <= 1:
        try:
            from app.services.memory_inject import build_memory_injection

            user_query = next(
                (str(m.get("content") or "") for m in reversed(messages)
                 if m.get("role") == "user"),
                "",
            )
            memory_system_extra, memory_user_extra = await build_memory_injection(
                db, user_id, cards[0][0], user_query
            )
        except Exception:
            memory_system_extra = memory_user_extra = ""
    if memory_system_extra:
        parts.append(memory_system_extra)

    if wb_before:
        parts.append("【世界设定（世界书·前置）】\n" + "\n".join(f"- {t}" for t in wb_before))

    # 群聊说话者选择（list/random 指定本轮发言角色）
    speaker = ""
    if group and len(cards) > 1:
        names_all = [c.get("name") or "?" for _, c in cards]
        if group_strategy == "list":
            turn = sum(1 for m in messages if m.get("role") == "assistant")
            speaker = names_all[turn % len(names_all)]
        elif group_strategy == "random":
            speaker = random.choice(names_all)

    if group and len(cards) > 1:
        if group_mode == "swap" and speaker:
            # SWAP：只注入当前说话者卡片，其余角色仅列名（省上下文）
            parts.append("你现在是一个多人角色扮演场景，其他角色在场但不发言：")
            others = [n for n in [c.get("name") or "?" for _, c in cards] if n != speaker]
            parts.append("（在场角色：" + "、".join(others) + "）")
            card = next(
                (c for _, c in cards if (c.get("name") or "?") == speaker), cards[0][1]
            )
            parts.append(f"本轮由你（【角色「{speaker}」】）发言：")
            parts.append(f"【角色外观与背景】\n{card.get('description', '')}")
            parts.append(f"【性格】\n{card.get('personality', '')}")
        else:
            parts.append("你现在是一个多人角色扮演场景，以下角色同时在场：")
            for _, card in cards:
                parts.append(
                    f"【角色「{card.get('name', '?')}」】\n"
                    f"外观背景：{card.get('description', '')}\n"
                    f"性格：{card.get('personality', '')}"
                )
    else:
        card = cards[0][1]
        main_prompt = str(card.get("system_prompt") or "").strip()
        if main_prompt:
            parts.append(substitute_macros(main_prompt, ctx))
        else:
            parts.append(f"你正在扮演角色「{card.get('name', '未知角色')}」。")
            parts.append(f"【角色外观与背景】\n{card.get('description', '')}")
            parts.append(f"【性格】\n{card.get('personality', '')}")
            parts.append(f"【初始场景】\n{card.get('scenario', '')}")
            phi = str(card.get("post_history_instructions") or "").strip()
            if phi:
                parts.append(f"【对话后指令】\n{phi}")

    # persona
    if persona and persona.description:
        parts.append(f"【你的身份】\n你是{persona.name}。{persona.description}")

    # 作者注（interval：每 N 条用户消息注入一次，默认 1 恒注入）
    if note and str(note.get("content") or "").strip():
        interval = int(note.get("interval") or 1)
        user_msg_count = sum(1 for m in messages if m.get("role") == "user")
        if interval <= 1 or user_msg_count % interval == 0:
            parts.append(f"【作者注】\n{str(note['content']).strip()}")

    # 世界书 after
    if wb_after:
        parts.append("【世界设定（世界书·后置）】\n" + "\n".join(f"- {t}" for t in wb_after))

    # 扮演要求
    if group and len(cards) > 1:
        if speaker:
            parts.append(
                f"【扮演要求】\n本轮必须由【角色「{speaker}」】发言，不要替其他角色说话；"
                "开头用『角色名』标注是谁在说话；不要跳出角色；回复长度适中；"
                "回复末尾用 [情绪:XX] 标注该角色的情绪（如开心/生气/害羞/平静）。"
            )
        else:
            parts.append(
                "【扮演要求】\n每次回复时，由其中一个角色回应（根据对话情境自然选择，轮换着来）；"
                "开头用『角色名』标注是谁在说话；不要跳出角色；回复长度适中；"
                "回复末尾用 [情绪:XX] 标注该角色的情绪（如开心/生气/害羞/平静）。"
            )
    else:
        parts.append(
            "【扮演要求】\n始终以角色身份回复，不要跳出角色；语言口语化自然；回复长度适中；"
            "回复末尾用 [情绪:XX] 标注当前情绪（如开心/生气/害羞/平静）。"
        )
    system_prompt = "\n\n".join(parts)

    # 示例对话（历史之前）
    example_parts: list[str] = []
    if not group or len(cards) <= 1:
        example_parts.append(_format_examples(cards[0][1]))
    else:
        for _, card in cards:
            ex = _format_examples(card)
            if ex:
                example_parts.append(ex)
    examples = "\n".join(example_parts)

    # 历史
    history = _format_history(messages, names)
    # atDepth 世界书条目：按深度插入历史中部（距末尾第 depth 条消息之后）
    if wb.at_depth:
        for hit in sorted(wb.at_depth, key=lambda h: h.depth, reverse=True):
            idx = max(0, len(history) - hit.depth)
            text = substitute_macros(hit.content, ctx)
            history.insert(idx, f"（世界书·深度注入@{hit.depth}）{text}")

    # 开场白（首轮且角色还没说过话）：优先 first_mes，可随机切到备用开场白
    intro = ""
    if not group or len(cards) <= 1:
        card = cards[0][1]
        if not any(m.get("role") != "user" for m in messages):
            greetings = _greeting_candidates(card)
            if greetings:
                intro = greetings[0] if len(greetings) == 1 else random.choice(greetings)

    # 续写模式：最后一条角色回复截断前半，作为续写起点
    if continue_mode and history and not history[-1].startswith("用户："):
        last = history.pop()
        if len(last) > 60:
            last = last[-60:]
        history.append(last)

    user_parts: list[str] = []
    if memory_user_extra:
        user_parts.append(memory_user_extra)
    if examples:
        user_parts.append(f"【示例对话（参考风格，不要照抄）】\n{examples}")
    if history:
        user_parts.append("\n".join(history))
    if intro:
        user_parts.append(f"{cards[0][1].get('name', '角色')}（开场白）：{intro}")

    # 群聊 nudge
    if group and len(cards) > 1:
        if speaker:
            user_parts.append(f"[Write the next reply only as {speaker}.]")
        else:
            user_parts.append("[Write the next reply only as the currently speaking character.]")
    if continue_mode:
        user_parts.append("请从上一条回复的末尾继续写下去，直接接续内容，不要重复已写部分，也不要寒暄。")
    else:
        user_parts.append("请继续对话：")
    user_prompt = "\n\n".join(user_parts)
    return system_prompt, user_prompt, wb.activated, speaker


# ==== 轻量记忆（自动摘要） ====

_MEMORY_SUMMARY_EVERY = 10  # 每 N 条消息生成一次摘要


def _chat_memory_summary(chat: Any) -> str:
    """读取会话已存摘要。"""
    from app.services import sessions as _s

    return str(_s.get_settings(chat).get("summary") or "")


async def _maybe_summarize(
    db: AsyncSession, user_id: str, chat: Any, model: str = ""
) -> None:
    """会话消息达到阈值时用当前模型生成摘要（失败静默，不阻塞主流程）。"""
    from app.services import sessions as _s

    messages = _s.chat_messages(chat)
    settings = _s.get_settings(chat)
    last_idx = int(settings.get("last_summarized_index") or 0)
    if len(messages) - last_idx < _MEMORY_SUMMARY_EVERY:
        return
    # 只摘要新增长的部分
    new_part = messages[last_idx:]
    text = "\n".join(
        f"{'用户' if m.get('role') == 'user' else '角色'}：{str(m.get('content') or '')[:200]}"
        for m in new_part
    )
    if len(text) < 60:
        return
    summary_prompt = (
        "请用 2-4 句话总结以下角色扮演对话的要点（人物关系、重要事件、角色当前状态），"
        "供后续对话保持连贯：\n" + text
    )
    try:
        resolved = await resolve_text_provider(db, model)
        provider = cast_text_provider(resolved.provider)
        result = await provider.generate(summary_prompt, resolved.model, max_tokens=256)
        summary = (result.content or "").strip()
        if summary:
            settings["summary"] = summary
            settings["last_summarized_index"] = len(messages)
            _s.set_settings(chat, settings)
    except Exception:
        # 摘要失败不阻断对话
        return


# ==== 主流程 ====

async def _get_persona(
    db: AsyncSession, user_id: str, persona_id: str | None
) -> RoleplayPersona | None:
    if not persona_id:
        return None
    return (
        await db.execute(
            select(RoleplayPersona).where(
                RoleplayPersona.id == persona_id, RoleplayPersona.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def roleplay_chat(
    db: AsyncSession,
    user_id: str,
    character_asset_ids: list[str],
    messages: list[dict[str, str]],
    model: str = "",
    group: bool = False,
    *,
    session_id: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    persona_id: str | None = None,
    note: dict[str, Any] | None = None,
    mode: str = "normal",
    swipe: bool = False,
    group_strategy: str = "natural",
    group_mode: str = "append",
) -> dict[str, Any]:
    """角色扮演对话：角色卡 → 世界书 → prompt → provider → 情绪 → 正则 → 落库。

    mode="continue"：续写上一条角色回复；swipe=True：生成备选回复（不落库、不追加历史）。
    """
    cards = await _load_cards(db, user_id, character_asset_ids)
    if not cards:
        return {"error": "角色卡不存在或无权访问"}
    persona = await _get_persona(db, user_id, persona_id)

    # 正则脚本（user_input：仅对最后一条用户消息生效于 prompt，不改存储）
    regex_scripts = await _load_regex_scripts(db, user_id)
    names = [c.get("name") or "角色" for _, c in cards]
    work_messages: list[dict[str, Any]] = list(messages)
    if work_messages and regex_scripts:
        last = dict(work_messages[-1])
        if last.get("role") == "user":
            last["content"] = _apply_regex(
                regex_scripts, str(last.get("content") or ""), "user_input", names
            )
            work_messages[-1] = last

    memory_summary = ""
    if session_id and not swipe:
        mem_chat = await sessions.get_chat(db, user_id, session_id)
        if mem_chat is not None:
            memory_summary = _chat_memory_summary(mem_chat)

    system_prompt, user_prompt, wb_activated, speaker = await _build_prompt(
        db,
        user_id,
        cards,
        work_messages,
        group=group,
        persona=persona,
        note=note,
        continue_mode=mode == "continue",
        group_strategy=group_strategy,
        group_mode=group_mode,
        memory_summary=memory_summary,
    )

    resolved = await resolve_text_provider(db, model)
    provider = cast_text_provider(resolved.provider)
    try:
        result = await provider.generate(
            user_prompt,
            resolved.model,
            system=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
        )
    except Exception as exc:
        # 上游错误（限流/超时/鉴权）友好返回，避免 500 卡死前端
        return {"error": f"生成失败：{str(exc)[:200]}"}
    reply = result.content or ""
    reply, mood = extract_mood(reply)
    if regex_scripts:
        reply = _apply_regex(regex_scripts, reply, "ai_output", names)
    mood_delta = _mood_delta(mood)
    from app.services.worldbook import estimate_tokens as _est_tok

    prompt_tokens = _est_tok(system_prompt) + _est_tok(user_prompt)

    # 自动触发的快捷回复（用户消息后建议）
    auto_replies: list[dict[str, str]] = []
    if not swipe and messages and messages[-1].get("role") == "user":
        last_user = str(messages[-1].get("content") or "")
        for qr in await _load_auto_quick_replies(db, user_id):
            msg = str(qr.message or "")
            if msg and msg != last_user:
                auto_replies.append({"label": qr.label, "message": msg})

    # 会话落库（swipe 备选不落库、不追加）
    chat_id: str | None = None
    if session_id and not swipe:
        chat = await sessions.get_chat(db, user_id, session_id)
        if chat is not None:
            if mode == "continue":
                # 续写：合并到最后一条 assistant 消息尾部
                msgs = sessions.chat_messages(chat)
                if msgs and msgs[-1].get("role") == "assistant":
                    msgs[-1]["content"] = str(msgs[-1]["content"]) + reply
                    await sessions.replace_messages(db, chat, msgs)
                else:
                    await sessions.append_message(
                        db, chat, {"role": "assistant", "content": reply, "mood": mood}
                    )
            else:
                # 用户消息仅在请求末尾确实是 user 且服务端尚未记录时才追加
                # （前端重试/完整历史回传时 messages[-1] 可能是 assistant）
                last_req = messages[-1] if messages else None
                stored = sessions.chat_messages(chat)
                if last_req and last_req.get("role") == "user" and (
                    not stored or stored[-1].get("content") != last_req.get("content")
                ):
                    await sessions.append_message(
                        db,
                        chat,
                        {"role": "user", "content": str(last_req.get("content") or "")},
                    )
                await sessions.append_message(
                    db, chat, {"role": "assistant", "content": reply, "mood": mood}
                )
            chat_id = chat.id

    # 轻量记忆：达到阈值后生成摘要（不阻塞）
    if chat_id:
        mem_chat = await sessions.get_chat(db, user_id, chat_id)
        if mem_chat is not None:
            await _maybe_summarize(db, user_id, mem_chat, model or resolved.model)

    # 多层记忆：L0 写入 gateway（fire-and-forget，不阻塞对话；群聊跳过）
    if chat_id and (not group or len(cards) <= 1):
        last_user = next(
            (str(m.get("content") or "") for m in reversed(messages)
             if m.get("role") == "user"),
            "",
        )
        _record_memory_turn(user_id, cards[0][0], chat_id, last_user, reply)

    return {
        "reply": reply,
        "mood": mood,
        "mood_delta": mood_delta,
        "character": {"names": [c.get("name", "角色") for _, c in cards]},
        "model": resolved.model,
        "chat_id": chat_id,
        "worldbook_hits": len(wb_activated),
        "prompt_tokens": prompt_tokens,
        "speaker": speaker,
        "auto_replies": auto_replies,
    }


async def roleplay_chat_stream(
    db: AsyncSession,
    user_id: str,
    character_asset_ids: list[str],
    messages: list[dict[str, str]],
    model: str = "",
    group: bool = False,
    *,
    session_id: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    persona_id: str | None = None,
    note: dict[str, Any] | None = None,
    group_strategy: str = "natural",
    group_mode: str = "append",
) -> AsyncIterator[dict[str, Any]]:
    """流式角色扮演：yield {type: "chunk", content} / {type: "done", reply, mood, ...}。"""
    cards = await _load_cards(db, user_id, character_asset_ids)
    if not cards:
        yield {"type": "error", "error": "角色卡不存在或无权访问"}
        return
    persona = await _get_persona(db, user_id, persona_id)
    regex_scripts = await _load_regex_scripts(db, user_id)
    names = [c.get("name") or "角色" for _, c in cards]
    work_messages: list[dict[str, Any]] = list(messages)
    if work_messages and regex_scripts:
        last = dict(work_messages[-1])
        if last.get("role") == "user":
            last["content"] = _apply_regex(
                regex_scripts, str(last.get("content") or ""), "user_input", names
            )
            work_messages[-1] = last

    system_prompt, user_prompt, wb_activated, speaker = await _build_prompt(
        db,
        user_id,
        cards,
        work_messages,
        group=group,
        persona=persona,
        note=note,
        group_strategy=group_strategy,
        group_mode=group_mode,
    )
    resolved = await resolve_text_provider(db, model)
    provider = cast_text_provider(resolved.provider)

    chunks: list[str] = []
    try:
        async for delta in provider.stream_generate(
            user_prompt,
            resolved.model,
            system=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
        ):
            chunks.append(delta)
            yield {"type": "chunk", "content": delta}
    except Exception as exc:
        yield {"type": "error", "error": f"生成失败：{str(exc)[:200]}"}
        return

    reply = "".join(chunks)
    reply, mood = extract_mood(reply)
    if regex_scripts:
        reply = _apply_regex(regex_scripts, reply, "ai_output", names)
    mood_delta = _mood_delta(mood)

    # 自动触发的快捷回复
    auto_replies: list[dict[str, str]] = []
    if messages and messages[-1].get("role") == "user":
        last_user = str(messages[-1].get("content") or "")
        for qr in await _load_auto_quick_replies(db, user_id):
            msg = str(qr.message or "")
            if msg and msg != last_user:
                auto_replies.append({"label": qr.label, "message": msg})

    from app.services.worldbook import estimate_tokens as _est_tok

    chat_id: str | None = None
    if session_id:
        chat = await sessions.get_chat(db, user_id, session_id)
        if chat is not None:
            await sessions.append_message(
                db, chat, {"role": "user", "content": str(messages[-1].get("content") or "")}
            )
            await sessions.append_message(
                db, chat, {"role": "assistant", "content": reply, "mood": mood}
            )
            chat_id = chat.id

    # 多层记忆：L0 写入 gateway（fire-and-forget；群聊跳过）
    if chat_id and (not group or len(cards) <= 1):
        last_user = str(messages[-1].get("content") or "") if messages else ""
        _record_memory_turn(user_id, cards[0][0], chat_id, last_user, reply)

    yield {
        "type": "done",
        "reply": reply,
        "mood": mood,
        "mood_delta": mood_delta,
        "character": {"names": names},
        "model": resolved.model,
        "chat_id": chat_id,
        "worldbook_hits": len(wb_activated),
        "speaker": speaker,
        "auto_replies": auto_replies,
        "prompt_tokens": _est_tok(system_prompt) + _est_tok(user_prompt),
    }


def cast_text_provider(provider: Any) -> TextProvider:
    from typing import cast

    return cast(TextProvider, provider)


# ==== 兼容层：_build_system_prompt（单角色，供旧测试/调用方） ====

async def _build_system_prompt(
    db: AsyncSession, card: dict[str, Any], recent_messages: list[str]
) -> str:
    """单角色 system prompt（旧签名兼容）。"""
    parts = [
        f"你正在扮演角色「{card.get('name', '未知角色')}」。",
        f"【角色外观与背景】\n{card.get('description', '')}",
        f"【性格】\n{card.get('personality', '')}",
        f"【初始场景】\n{card.get('scenario', '')}",
        "【扮演要求】\n始终以角色身份回复，不要跳出角色；语言口语化自然；回复长度适中。",
    ]
    first_mes = card.get("first_mes", "")
    if first_mes:
        parts.append(f"【开场白】\n对话开始时，由你先说出这句话（之后不再重复）：\n{first_mes}")
    lore_hits = await _match_lore(db, str(card.get("name", "")), recent_messages)
    if lore_hits:
        parts.append(
            "【世界设定（世界书）】\n"
            + "\n".join(f"- {h}" for h in lore_hits)
            + "\n以上设定在对话中保持一致。"
        )
    return "\n\n".join(parts)
