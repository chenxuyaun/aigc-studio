"""Music 路由层（P1-1 薄接口层）。

P1-1 后：业务机器已抽至 core.runtime.music 包：
- style.py      风格画像/检测          - quality.py  歌词结构修复/自检/十三辙韵表
- textproc.py   LLM JSON 容错/转写     - prompts.py  全部提示词模板
- engine.py     文本 LLM 编排（写歌质量闭环/圆桌引擎/心跳/限流）
- works.py      作品落库 + 知识库回填

本文件只保留：请求 schema + 11 个路由 handler（SSE 编排 glue）+ 兼容再导出
（tests / mission_service / music_assistant / scripts 仍可从本模块 import 旧名字）。
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.runtime.music import engine as music_engine
from app.core.runtime.music.engine import (  # noqa: F401  # 兼容再导出
    _ROUNDTABLE_RATE,
    _ROUNDTABLE_WINDOW,
    _extract_fix_list,
    _has_unresolved_conflict,
    _produce_final,
    _rate_limit_roundtable,
    _roundtable_hits,
    _with_heartbeat,
    build_agenda,
    default_cast,
    followup_reply,
    generate_json_with_retry,
    pad_cast,
    select_cast,
    speak_turn,
)
from app.core.runtime.music.prompts import (  # noqa: F401  # 兼容再导出
    _CAST_PROMPT,
    _COMPOSE_PROMPT,
    _DISCUSS_SYSTEM,
    _FINAL_PROMPT,
    _FIX_LIST_PROMPT,
    _ROUNDTABLE_PROMPT,
    _critic_task,
    _defense_task,
    _proposer_task,
    _supporter_task,
)
from app.core.runtime.music.quality import (  # noqa: F401  # 兼容再导出
    _is_antithetical_hook,
    _repair_lyrics,
    _segment_text,
    _severe_checks,
    _strip_tag,
    _syllable_count,
    _tail_char,
    _validate_lyrics,
)
from app.core.runtime.music.style import (  # noqa: F401  # 兼容再导出
    _STYLE_ALIASES,
    _STYLE_PROFILES,
    _detect_style,
    _style_profile_block,
)
from app.core.runtime.music.textproc import (  # noqa: F401  # 兼容再导出
    _extract_json,
    _shuffled_transcript,
    _transcript,
    _transcript_block,
)
from app.core.runtime.music.works import (  # noqa: F401  # 兼容再导出
    _BACKFILL_MIN_INTERVAL,
    _auto_save_work,
    _backfill_work_material,
)
from app.models.user import User
from app.schemas.generation import MusicGenerationRequest, TaskResponse
from app.security.auth import get_current_user
from app.services.generation_service import create_media_task
from app.services.text_utils import sse_event as _sse_event

router = APIRouter()


class MusicComposeRequest(BaseModel):
    """AI 写歌：主题 → 原创歌词 + 风格描述（供 Suno/网易天音等免费合成）。"""

    theme: str = Field(max_length=500)
    style: str = Field(default="流行", max_length=100)
    mood: str = Field(default="治愈", max_length=100)
    language: str = Field(default="中文", max_length=50)
    verse_count: int = Field(default=2, ge=1, le=4)
    model: str = ""  # 空 = 自动选择文本 Provider（cpa）


class MusicDiscussRequest(BaseModel):
    """音乐讨论室：多轮对话式共创（主题/歌词/编曲/乐理，AI 基于上下文迭代）。"""

    messages: list[dict[str, str]] = Field(min_length=1, max_length=30)
    style: str = Field(default="", max_length=100)  # 可选：固定风格后讨论
    use_web: bool = False  # 首轮注入联网素材（知识库不足时）
    model: str = ""


class MusicRoundtableRequest(BaseModel):
    """多角色圆桌：四位 AI 创作者（作词/作曲/制作/乐评）围绕主题相互讨论后定稿。"""

    theme: str = Field(max_length=500)
    style: str = Field(default="", max_length=100)  # 可选：指定风格基调
    mood: str = Field(default="", max_length=100)  # 可选：情绪基调
    quick: bool = False  # 快速模式：3 轮迷你讨论（约 25 秒）
    use_web: bool = False  # 知识库命中不足时联网搜索兜底（新鲜题材）
    model: str = ""


class MusicFollowupRequest(BaseModel):
    """圆桌定稿后追问：全员基于讨论+定稿回应一个问题，产出新定稿。"""

    theme: str = Field(max_length=500)
    style: str = Field(default="", max_length=100)
    cast: list[dict[str, Any]] = Field(default_factory=list)
    rounds: list[dict[str, str]] = Field(default_factory=list)
    final: dict[str, Any] | None = None
    question: str = Field(min_length=1, max_length=500)
    use_web: bool = False  # 追问轮同样可补充联网素材
    model: str = ""


class MusicToChatRequest(BaseModel):
    """把作品发布到创作群。"""

    chat_id: str = Field(min_length=8, max_length=64)


class MusicWorkSaveRequest(BaseModel):
    """手动保存一首作品（写歌/讨论室成品）。"""

    title: str = Field(default="未命名", max_length=100)
    theme: str = Field(default="", max_length=500)
    style: str = Field(default="", max_length=100)
    lyrics: str = Field(default="", max_length=20000)
    arrangement: str = Field(default="", max_length=10000)
    style_en: str = Field(default="", max_length=5000)
    rounds: list[dict[str, str]] | None = None
    source: str = Field(default="roundtable", max_length=20)


@router.post("/compose", response_model=None)
async def compose_song(
    req: MusicComposeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """AI 写歌（免费）：主题 → 原创歌词 + 风格描述 JSON。走平台文本 Provider（cpa）。"""
    # 词曲专业常驻注入：单次写歌同样带上创作技法（专业地基）
    extra_prompt_block = ""
    try:
        from app.services.knowledge_materials import retrieve_music_pro_notes

        pro_notes = await retrieve_music_pro_notes(db, user.id)
        if pro_notes:
            extra_prompt_block = "\n\n" + pro_notes
    except Exception:
        pass
    return await music_engine.compose_song(db, req, extra_prompt_block=extra_prompt_block)


@router.post("/discuss")
async def discuss_music(
    req: MusicDiscussRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """音乐讨论室：多轮对话式创作（自由讨论，歌词可复制）。

    首轮（对话刚开始）自动注入创作素材：知识库优先，勾选联网则补充新鲜题材。
    """
    if not req.style:
        # 未显式固定风格时，从对话文本检测（"写首民谣"→民谣特征注入讨论）
        req.style = _detect_style(
            " ".join(m.get("content", "") for m in req.messages[-6:] if m.get("content"))
        )
    prompt = _transcript(req.messages, req.style)
    if req.style:
        prompt = prompt + _style_profile_block(req.style)
    # 首轮注入创作素材（从用户最新消息提取主题；后续轮次素材已在对话上下文里）
    if len(req.messages) <= 2:
        theme = next(
            (m.get("content") or "" for m in reversed(req.messages) if m.get("role") == "user"),
            "",
        ).strip()[:100]
        if theme:
            try:
                from app.services.knowledge_materials import retrieve_creation_materials

                kb_text, _kt, web_text, _wt = await retrieve_creation_materials(
                    db, user.id, theme, limit=3, use_web=req.use_web
                )
                from app.services.knowledge_materials import format_material_block

                block = format_material_block(kb_text, web_text)
                if block:
                    prompt += block
            except Exception:
                pass
    reply, provider_model = await music_engine.discuss_reply(
        db, prompt=prompt, model=req.model, system=_DISCUSS_SYSTEM
    )
    return {"reply": reply, "provider": provider_model}


@router.post("/roundtable")
async def roundtable_music(
    req: MusicRoundtableRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """多角色圆桌（单次版）：四位 AI 创作者相互讨论后定稿（用户只需给主题）。"""
    style = req.style or _detect_style(req.theme)
    return await music_engine.roundtable_single(
        db, theme=req.theme, style=style, mood=req.mood, model=req.model
    )


@router.post("/roundtable/stream")
async def roundtable_stream(
    req: MusicRoundtableRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """多角色圆桌·真讨论版（SSE）：每位发言者实时生成（携带前序发言），最后定稿。"""

    async def _gen() -> AsyncIterator[str]:
        # 限流：每用户每分钟最多 3 场（成本保护）
        if not _rate_limit_roundtable(user.id):
            err = {
                "type": "error",
                "error": "圆桌会议开得太频繁了，请等一分钟再开（每用户每分钟 3 场）",
            }
            yield _sse_event(err)
            yield "data: [DONE]\n\n"
            return
        # 风格基调：显式指定优先；未指定时从主题文本自动检测（"矿工清晨的叙事民谣"→民谣）
        style = req.style or _detect_style(req.theme)
        # 创作素材：知识库（已读懂）优先；命中不足且开启联网时，搜索兜底新鲜题材
        materials = ""
        material_titles: list[str] = []
        web_materials = ""
        try:
            from app.services.knowledge_materials import retrieve_creation_materials

            (
                materials,
                material_titles,
                web_materials,
                web_titles,
            ) = await retrieve_creation_materials(
                db, user.id, req.theme, limit=3, use_web=req.use_web
            )
            material_titles = material_titles + web_titles
        except Exception:
            materials = ""
        from app.services.knowledge_materials import format_material_block

        kb_block = format_material_block(materials, web_materials)
        # 成长档案：用户创作偏好注入（风格/主题倾向贴合用户习惯）
        try:
            from app.services.profile_service import build_profile_text

            profile_block = await build_profile_text(db, user.id)
            if profile_block:
                kb_block += "\n\n" + profile_block
        except Exception:
            pass
        # 词曲专业常驻注入：无论主题，带上创作技法文档（专业地基，让模型边查边写）
        try:
            from app.services.knowledge_materials import retrieve_music_pro_notes

            pro_notes = await retrieve_music_pro_notes(db, user.id)
            if pro_notes:
                kb_block += "\n\n" + pro_notes
        except Exception:
            pass
        yield _sse_event({"type": "materials", "titles": material_titles})
        # 第 0 轮：AI 按主题定制会议阵容（4 位专业角色）
        yield _sse_event({"type": "cast_start"})
        cast_prompt = (
            _CAST_PROMPT.format(theme=req.theme, style=style or "（自由）")
            + _style_profile_block(style)
            + kb_block
        )
        cast_list = await select_cast(db, model=req.model, cast_prompt=cast_prompt)
        if not cast_list:
            cast_list = default_cast()
        cast_list = pad_cast(cast_list)
        ordered = sorted(cast_list, key=lambda r: int(r.get("order") or 99))
        yield _sse_event({"type": "cast", "cast": cast_list})

        # 对抗式议程：提案 → 反驳 → 辩护 → 补充（quick 模式跳过补充，裁决在定稿轮）
        core, supporters = build_agenda(ordered)

        rounds: list[dict[str, str]] = []

        async def _run_turn(item: dict[str, Any]) -> str:
            # 自我中心投影：只给上一个对手的原话（不全文拼接，防复读套话）
            opponent_block = ""
            if rounds:
                opp = rounds[-1]
                opponent_block = f"{opp['speaker']}：{opp['content']}"
            return await speak_turn(
                db,
                model=req.model,
                theme=req.theme,
                style=style,
                item=item,
                opponent_block=opponent_block,
                kb_block=kb_block,
            )

        for idx, item in enumerate(core, start=1):
            role = item["role"]
            speaker = str(role.get("name") or f"专家{idx}")
            yield _sse_event({"type": "round_start", "speaker": speaker, "round_no": idx})
            text = ""
            async for ev in _with_heartbeat(lambda it=item: _run_turn(it)):
                if isinstance(ev, tuple):
                    text = ev[1]
                else:
                    yield _sse_event(ev)
            rounds.append({"speaker": speaker, "content": text})
            yield _sse_event({"type": "round", "speaker": speaker, "content": text})

        # 需求6：共识检测——辩护后仍有分歧才跑补充轮（共识就停，不固定轮次）
        if not req.quick and supporters:
            has_conflict = await _has_unresolved_conflict(db, req.theme, rounds)
            if has_conflict:
                for sup in supporters:
                    item = {
                        "role": sup,
                        "task": _supporter_task(),
                        "stance": "你默认怀疑前文，专业判断优先，不人云亦云。",
                    }
                    speaker = str(sup.get("name") or "补充")
                    yield _sse_event(
                        {"type": "round_start", "speaker": speaker, "round_no": len(rounds) + 1}
                    )
                    text = ""
                    async for ev in _with_heartbeat(lambda it=item: _run_turn(it)):
                        if isinstance(ev, tuple):
                            text = ev[1]
                        else:
                            yield _sse_event(ev)
                    rounds.append({"speaker": speaker, "content": text})
                    yield _sse_event({"type": "round", "speaker": speaker, "content": text})

        # 定稿轮：主理人主编把关 + 自检 + 严重问题自动重写一轮 + 自动存入「我的作品」
        finalizer = next(
            (r for r in ordered if r.get("finalizer")), ordered[0] if ordered else None
        )
        yield _sse_event({"type": "final_start"})
        final: dict[str, Any] = {}
        checks: list[str] = []
        async for ev in _with_heartbeat(
            lambda: _produce_final(
                db,
                theme=req.theme,
                style=style,
                finalizer=finalizer,
                rounds=rounds,
                kb_block=kb_block,
            )
        ):
            if isinstance(ev, tuple):
                final, checks = ev[1]
            else:
                yield _sse_event(ev)
        rewrote = False
        if not final.get("error") and _severe_checks(checks):
            rewrote = True
            first_checks = checks  # 绑定本轮自检警告（避免闭包晚绑定到重写轮的 checks）
            async for ev in _with_heartbeat(
                lambda fc=first_checks: _produce_final(
                    db,
                    theme=req.theme,
                    style=style,
                    finalizer=finalizer,
                    rounds=rounds,
                    kb_block=kb_block,
                    rewrite_warnings=fc,
                )
            ):
                if isinstance(ev, tuple):
                    final, checks = ev[1]
                else:
                    yield _sse_event(ev)
        work_id = ""
        if not final.get("error"):
            try:
                work_id = await _auto_save_work(
                    db,
                    user_id=user.id,
                    theme=req.theme,
                    style=style,
                    final=final,
                    rounds=rounds,
                    source="roundtable",
                )
            except Exception:
                work_id = ""
            # 好作品自动回填知识库（创作范例）：平台自己长素材——「继续学」自动化
            if work_id and not _severe_checks(checks):
                with contextlib.suppress(Exception):
                    backfill_task = asyncio.create_task(
                        _backfill_work_material(
                            user_id=user.id,
                            work_title=str(final.get("title") or "")[:60],
                            theme=req.theme,
                            lyrics=str(final.get("lyrics") or ""),
                            chords=str(final.get("chords") or ""),
                            arrangement=str(final.get("arrangement") or ""),
                        )
                    )
                    backfill_task.add_done_callback(lambda _t: None)
        yield _sse_event(
            {
                "type": "final",
                "final": final,
                "rounds": rounds,
                "cast": cast_list,
                "checks": checks,
                "work_id": work_id,
                "rewrote": rewrote,
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post("/roundtable/followup")
async def roundtable_followup(
    req: MusicFollowupRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """圆桌定稿后追问：全员基于讨论+定稿+问题各回应一句，产出新定稿（SSE）。"""

    async def _gen() -> AsyncIterator[str]:
        if not _rate_limit_roundtable(user.id):
            yield _sse_event(
                {"type": "error", "error": "操作太频繁了，请等一分钟再试（每用户每分钟 3 场）"}
            )
            yield "data: [DONE]\n\n"
            return
        # 风格基调：沿用定稿风格；未指定时从主题检测
        style = req.style or _detect_style(req.theme)
        # 创作素材（与主会议一致）：知识库优先，追问轮勾选联网则补充新鲜题材
        kb_block = ""
        try:
            from app.services.knowledge_materials import retrieve_creation_materials

            materials, _kt, web_materials, _wt = await retrieve_creation_materials(
                db, user.id, req.theme, limit=2, use_web=req.use_web
            )
            from app.services.knowledge_materials import format_material_block

            kb_block = format_material_block(materials, web_materials)
        except Exception:
            kb_block = ""
        try:
            from app.services.knowledge_materials import retrieve_music_pro_notes

            pro_notes = await retrieve_music_pro_notes(db, user.id)
            if pro_notes:
                kb_block += "\n\n" + pro_notes
        except Exception:
            pass
        cast = req.cast or []
        ordered = sorted(cast, key=lambda r: int(r.get("order") or 99))
        if not ordered:
            ordered = default_cast()
        prev_final = req.final or {}
        prev_lyrics = str(prev_final.get("lyrics") or "")

        rounds: list[dict[str, str]] = list(req.rounds or [])
        base = _transcript_block(rounds, limit=1800)
        for idx, role in enumerate(ordered, start=1):
            speaker = str(role.get("name") or f"专家{idx}")
            yield _sse_event({"type": "round_start", "speaker": speaker, "round_no": idx})
            persona = f"你是{role.get('name')}（{role.get('field')}）：{role.get('persona')}"
            task = (
                f"听众对定稿提出了新要求：{req.question}。"
                "基于这场讨论与定稿，从你的专业领域回应：给出具体调整方案"
                "（改词/换意象/调和声/改配器，必须可落地），60-100 字。"
            )
            prompt = (
                f"创作主题：{req.theme}\n"
                f"风格基调：{style or '（自由）'}\n"
                f"{_style_profile_block(style)}"
                f"{kb_block}"
                f"\n\n【前序讨论】\n{base or '（无）'}\n\n"
                f"【当前定稿歌词】\n{prev_lyrics[:1500]}\n\n"
                f"【本轮任务】{task}"
            )

            async def _reply(p: str = prompt, pe: str = persona) -> str:
                return await followup_reply(db, model=req.model, prompt=p, persona=pe)

            text = ""
            async for ev in _with_heartbeat(_reply):
                if isinstance(ev, tuple):
                    text = ev[1]
                else:
                    yield _sse_event(ev)
            rounds.append({"speaker": speaker, "content": text})
            yield _sse_event({"type": "round", "speaker": speaker, "content": text})

        # 新定稿：基于原定稿 + 全员回应
        finalizer = next(
            (r for r in ordered if r.get("finalizer")), ordered[0] if ordered else None
        )
        yield _sse_event({"type": "final_start"})
        finalizer_name = str((finalizer or {}).get("name") or "主理人")
        transcript = _transcript_block(rounds, limit=2000)
        followup_prompt = _FINAL_PROMPT.format(
            name=finalizer_name,
            field=str((finalizer or {}).get("field") or "音乐制作"),
            theme=req.theme,
            style=style or "（自由）",
            style_profile=_style_profile_block(style),
            transcript=(
                f"【听众新要求】{req.question}\n\n"
                f"【原定稿】\n{prev_lyrics[:1500]}\n\n"
                f"【讨论记录】\n{transcript}"
            ),
        )
        final: dict[str, Any] = {}
        async for ev in _with_heartbeat(
            lambda: generate_json_with_retry(
                db, model=req.model, prompt=followup_prompt, temperature=0.7
            )
        ):
            if isinstance(ev, tuple):
                final = ev[1]
            else:
                yield _sse_event(ev)
        if not final.get("error"):
            final["lyrics"] = _repair_lyrics(str(final.get("lyrics") or ""))
        checks = [] if final.get("error") else _validate_lyrics(str(final.get("lyrics") or ""))
        work_id = ""
        if not final.get("error"):
            try:
                work_id = await _auto_save_work(
                    db,
                    user_id=user.id,
                    theme=req.theme,
                    style=style,
                    final=final,
                    rounds=rounds,
                    source="roundtable",
                )
            except Exception:
                work_id = ""
        yield _sse_event(
            {
                "type": "final",
                "final": final,
                "rounds": rounds,
                "cast": cast,
                "checks": checks,
                "work_id": work_id,
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/works")
async def list_music_works(
    q: str = Query(default="", max_length=100),
    tag: str = Query(default="", max_length=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """我的音乐作品列表（q 按标题/主题/风格过滤；tag 按标签过滤）。"""
    from app.services.music_works import list_works

    return {"items": await list_works(db, user.id, q=q, tag=tag)}


@router.post("/works")
async def save_music_work(
    req: MusicWorkSaveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """手动保存一首作品（写歌/讨论室成品）。"""
    from app.services.music_works import save_work

    work = await save_work(
        db,
        user_id=user.id,
        title=req.title,
        theme=req.theme,
        style=req.style,
        lyrics=req.lyrics,
        arrangement=req.arrangement,
        style_en=req.style_en,
        rounds=req.rounds,
        source=req.source,
    )
    return {"id": work.id, "title": work.title}


@router.get("/works/{work_id}/public")
async def public_music_work(
    work_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """公开只读分享（分享链接用，返回作品内容不含用户信息）。"""
    from app.models.music_work import MusicWork

    work = await db.get(MusicWork, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    return {
        "id": work.id,
        "title": work.title,
        "theme": work.theme,
        "style": work.style,
        "lyrics": work.lyrics,
        "chords": work.chords,
        "arrangement": work.arrangement,
        "style_en": work.style_en,
        "source": work.source,
        "created_at": str(work.created_at) if work.created_at else "",
    }


@router.post("/works/{work_id}/to-chat")
async def publish_work_to_chat(
    work_id: str,
    req: MusicToChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """把作品发布到创作群（作为消息进群，群成员可见）。"""
    from app.models.music_work import MusicWork
    from app.services import sessions

    work = await db.get(MusicWork, work_id)
    if work is None or work.user_id != user.id:
        raise HTTPException(status_code=404, detail="作品不存在")
    chat = await sessions.get_chat(db, user.id, req.chat_id)
    if chat is None or not chat.is_room:
        raise HTTPException(status_code=404, detail="群不存在或无权访问")
    block = [
        f"🎵 主题曲《{work.title}》",
        "",
        work.lyrics,
    ]
    if work.chords:
        block.append("")
        block.append(f"🎸 和弦谱：{work.chords}")
    if work.arrangement:
        block.append("")
        block.append(f"🎧 编曲：{work.arrangement}")
    await sessions.append_message(db, chat, {"role": "assistant", "content": "\n".join(block)})
    await db.commit()
    return {"ok": True, "chat_id": chat.id, "title": work.title}


@router.delete("/works/{work_id}")
async def delete_music_work(
    work_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """删除一首作品。"""
    from app.services.music_works import delete_work

    deleted = await delete_work(db, user.id, work_id)
    return {"ok": deleted}


@router.post("/generate", response_model=TaskResponse)
async def generate_music(
    req: MusicGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskResponse:
    """音乐生成任务（MusicGen 等 HF 音频模型，prompt 描述风格/情绪/乐器）。"""
    task = await create_media_task(
        db, user_id=user.id, task_type="music", model=req.model, params=req
    )
    return TaskResponse.model_validate(task)
