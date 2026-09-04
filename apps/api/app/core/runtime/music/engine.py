"""Core Runtime - Music 文本 LLM 编排引擎（P1-1 从 api/v1/generations/music.py 抽离）。

- 限流：_rate_limit_roundtable（每用户每分钟 3 场，成本保护）
- 写歌：compose_song（含质量闭环 _quality_gate：修复→自检→严重问题自动重写一轮）
- 圆桌：select_cast（选角）/ default_cast + pad_cast（兜底）/ build_agenda（对抗式议程）
        / speak_turn（逐轮发言，重试 3 次）/ _has_unresolved_conflict（共识检测）
        / _extract_fix_list（批评→替代清单）/ _produce_final（定稿轮）
- 基建：generate_json_with_retry（定稿类 JSON 重试）/ _with_heartbeat（SSE 心跳防超时断流）

本模块是测试 patch `resolve_text_provider` 的统一切点。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from app.core.runtime.music.prompts import (
    _COMPOSE_PROMPT,
    _FINAL_PROMPT,
    _FIX_LIST_PROMPT,
    _ROUNDTABLE_PROMPT,
    _critic_task,
    _defense_task,
    _proposer_task,
    _speaker_prompt,
)
from app.core.runtime.music.quality import _repair_lyrics, _severe_checks, _validate_lyrics
from app.core.runtime.music.style import _STYLE_PROFILES, _style_profile_block
from app.core.runtime.music.textproc import (
    _extract_json,
    _shuffled_transcript,
    _transcript_block,
)
from app.services.provider_resolver import resolve_text_provider
from app.services.text_utils import result_text as _provider_text
from sqlalchemy.ext.asyncio import AsyncSession

class MusicComposeRequest(BaseModel):
    """AI 写歌请求（引擎输入契约；P4 从 api 层迁入，路由层沿用此定义保 HTTP 契约不变）。"""

    theme: str = Field(max_length=500)
    style: str = Field(default="流行", max_length=100)
    mood: str = Field(default="治愈", max_length=100)
    language: str = Field(default="中文", max_length=50)
    verse_count: int = Field(default=2, ge=1, le=4)
    model: str = ""  # 空 = 自动选择文本 Provider（cpa）


# 圆桌限流：每用户每分钟最多 3 场（一场 8 次 LLM 调用，成本保护）
_ROUNDTABLE_RATE = 3
_ROUNDTABLE_WINDOW = 60.0
_roundtable_hits: dict[str, list[float]] = {}


def _rate_limit_roundtable(user_id: str) -> bool:
    """滑动窗口限流：返回 False 表示超限。"""
    import time

    now = time.monotonic()
    hits = [t for t in _roundtable_hits.get(user_id, []) if now - t < _ROUNDTABLE_WINDOW]
    if len(hits) >= _ROUNDTABLE_RATE:
        _roundtable_hits[user_id] = hits
        return False
    hits.append(now)
    _roundtable_hits[user_id] = hits
    return True


async def generate_json_with_retry(
    db: AsyncSession,
    *,
    model: str = "",
    prompt: str,
    temperature: float = 0.7,
    attempts: int = 3,
) -> dict[str, Any]:
    """定稿类 JSON 生成：上游抖动/JSON 解析失败都重试（定稿是整场会议的收尾，失败代价高）。

    全部失败返回 {"error": "定稿失败：..."}；成功返回解析后的 dict。
    """
    resolved = await resolve_text_provider(db, model)
    final: dict[str, Any] = {"error": "定稿失败：上游异常"}
    for attempt in range(attempts):
        try:
            result = await resolved.provider.generate(  # type: ignore[attr-defined]
                prompt, resolved.model, temperature=temperature
            )
            candidate = _extract_json(_provider_text(result))
            if candidate.get("error"):
                raise ValueError(str(candidate.get("raw") or candidate["error"])[:120])
            return candidate
        except Exception as exc:
            if attempt < attempts - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
            final = {"error": f"定稿失败：{str(exc)[:80]}"}
    return final


async def _load_voice_dna(db: AsyncSession, user_id: str | None) -> dict | None:
    """取用户文风档案 voice_dna（失败/无档案静默降级 None，不影响创作主流程）。"""
    if not user_id:
        return None
    try:
        from app.applications.voice_service import get_profile

        profile = await get_profile(db, user_id)
        return (profile.voice_dna or {}) if profile else None
    except Exception:
        return None


async def _load_experience(db: AsyncSession, user_id: str | None) -> str:
    """取用户真实经历素材块（长期记忆 event/emotion 类；失败/无素材空串，静默降级）。"""
    if not user_id:
        return ""
    try:
        from app.applications.experience_injector import build_experience_prompt

        return await build_experience_prompt(db, user_id)
    except Exception:
        return ""


def _ai_voice_checks(text: str, voice_dna: dict | None) -> list[str]:
    """AI 腔 + 个人文风对照自检（对照用户档案的优选/忌讳/节奏），命中返回警告列表。

    仅作检测警告，不触发自动重写（歌词重写轮由结构缺陷决定，避免误伤口语化表达）。
    """
    try:
        from app.applications.ai_voice_checker import check_ai_voice

        issues = check_ai_voice(text, voice_dna)
    except Exception:
        return []
    serious = [i for i in issues if i["level"] in ("high", "medium")]
    if not serious:
        return []
    voice_avoid = [i for i in serious if i["kind"] == "voice_avoid"]
    if voice_avoid:
        return [f"文风档案忌讳的表达出现在歌词中（{voice_avoid[0]['sample'][:20]}…）——换成你自己的说法"]
    samples = "、".join(i["sample"][:12] for i in serious[:3])
    return [f"AI 腔过重（{len(serious)} 处：{samples}…）——歌词是能唱的人话，删掉套话/机械句式/宣传腔"]


async def _quality_gate(
    resolved: Any, prompt: str, *, voice_dna: dict | None = None
) -> dict[str, Any]:
    """质量闭环：生成 → 解析 → 结构修复 → 自检 → 严重问题自动重写一轮。

    compose（单次写歌）与圆桌单次版共用同一套把关（与圆桌定稿同源）。
    voice_dna（可选）：当前用户文风档案，提供时追加「个人忌讳/节奏不符」AI 腔自检。
    """
    # 温度 0.95：增加每次生成的风格/表达差异（避免"都是一个调调"）
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        prompt, resolved.model, temperature=0.95
    )
    if isinstance(result, dict):
        text = str(result.get("text") or result.get("content") or "")
    elif hasattr(result, "content"):
        text = str(result.content)
    else:
        text = str(result)
    data = _extract_json(text)
    data["provider"] = resolved.model
    # 质量闭环：结构修复 + 自检 + 严重问题自动重写一轮
    if not data.get("error"):
        data["lyrics"] = _repair_lyrics(str(data.get("lyrics") or ""))
    checks = [] if data.get("error") else _validate_lyrics(str(data.get("lyrics") or ""))
    if voice_dna:
        checks += _ai_voice_checks(str(data.get("lyrics") or ""), voice_dna)
    data["checks"] = checks
    if not data.get("error") and _severe_checks(checks):
        rewrite_prompt = (
            prompt
            + "\n\n【上一轮自检警告】（本次为修正轮：必须逐条修正下列问题后再输出定稿，"
            "修正后的作品不得再出现同类问题）\n"
            + "\n".join(f"- {w}" for w in checks)
        )
        try:
            r2 = await resolved.provider.generate(  # type: ignore[attr-defined]
                rewrite_prompt, resolved.model, temperature=0.7
            )
            data2 = _extract_json(_provider_text(r2))
            if not data2.get("error"):
                data2["lyrics"] = _repair_lyrics(str(data2.get("lyrics") or ""))
                checks2 = _validate_lyrics(str(data2.get("lyrics") or ""))
                if voice_dna:
                    checks2 += _ai_voice_checks(str(data2.get("lyrics") or ""), voice_dna)
                data2["checks"] = checks2
                data2["rewrote"] = True
                data2["provider"] = resolved.model
                data = data2
        except Exception:
            pass  # 重写失败保留初稿（自检警告已在 checks 返回）
    return data


async def compose_song(
    db: AsyncSession, req: Any, *, extra_prompt_block: str = "", user_id: str | None = None
) -> dict[str, Any]:
    """AI 写歌（免费）：主题 → 原创歌词 + 风格描述 JSON。走平台文本 Provider（cpa）。

    extra_prompt_block：调用方（路由/mission）注入的创作素材块（词曲专业常驻笔记等）。
    user_id：当前用户 id（可选），用于对照文风档案做 AI 腔自检（静默降级）。
    """
    style_profile = _STYLE_PROFILES.get(req.style, _STYLE_PROFILES["流行"])
    prompt = _COMPOSE_PROMPT.format(
        theme=req.theme,
        style=req.style,
        mood=req.mood,
        language=req.language,
        verse_count=req.verse_count,
        style_profile=style_profile,
    )
    if extra_prompt_block:
        prompt += extra_prompt_block
    exp = await _load_experience(db, user_id)
    if exp:
        prompt += "\n\n" + exp
    resolved = await resolve_text_provider(db, req.model)
    voice_dna = await _load_voice_dna(db, user_id)
    return await _quality_gate(resolved, prompt, voice_dna=voice_dna)


async def roundtable_single(
    db: AsyncSession,
    *,
    theme: str,
    style: str,
    mood: str,
    model: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """多角色圆桌（单次版）：四位 AI 创作者相互讨论后定稿（用户只需给主题）。"""
    prompt = _ROUNDTABLE_PROMPT.format(
        theme=theme,
        style=style or "（自由，由讨论决定）",
        mood=mood or "（自由，由讨论决定）",
    ) + _style_profile_block(style)
    exp = await _load_experience(db, user_id)
    if exp:
        prompt += "\n\n" + exp
    resolved = await resolve_text_provider(db, model)
    voice_dna = await _load_voice_dna(db, user_id)
    return await _quality_gate(resolved, prompt, voice_dna=voice_dna)


async def discuss_reply(
    db: AsyncSession, *, prompt: str, model: str, system: str
) -> tuple[str, str]:
    """音乐讨论室单轮回复。返回 (reply_text, provider_model)。"""
    resolved = await resolve_text_provider(db, model)
    result = await resolved.provider.generate(  # type: ignore[attr-defined]
        prompt, resolved.model, system=system, temperature=0.95
    )
    if isinstance(result, dict):
        text = str(result.get("text") or result.get("content") or "")
    elif hasattr(result, "content"):
        text = str(result.content)
    else:
        text = str(result)
    return text, resolved.model


async def select_cast(
    db: AsyncSession, *, model: str, cast_prompt: str
) -> list[dict[str, Any]]:
    """第 0 轮：AI 按主题定制会议阵容。

    选角质量校验：通用占位（「专家N」/空 persona）视为发挥波动 → 重试一次；
    两次都不合格返回空列表，由调用方走 default_cast 兜底。
    """
    resolved = await resolve_text_provider(db, model)
    cast_list: list[dict[str, Any]] = []
    for _attempt in range(2):
        try:
            cast_result = await resolved.provider.generate(  # type: ignore[attr-defined]
                cast_prompt, resolved.model, temperature=0.9
            )
            cast_data = _extract_json(_provider_text(cast_result))
            roles = cast_data.get("roles") or []
            if isinstance(roles, list) and len(roles) >= 2:
                cast_list = [
                    {
                        "name": str(r.get("name") or f"专家{idx}")[:20],
                        "field": str(r.get("field") or "音乐创作")[:40],
                        "persona": str(r.get("persona") or "")[:300],
                        "icon": str(r.get("icon") or "🎙️")[:4],
                        "order": int(r.get("order") or idx + 1),
                        "finalizer": bool(r.get("finalizer")),
                    }
                    for idx, r in enumerate(roles[:4])
                ]
                generic = sum(
                    1
                    for c in cast_list
                    if str(c["name"]).startswith("专家") or not c["persona"].strip()
                )
                if generic < max(1, len(cast_list) // 2):
                    break  # 定制合格
            cast_list = []  # 通用占位/数量不足 → 重试或 fallback
        except Exception:
            cast_list = []
    return cast_list


def default_cast() -> list[dict[str, Any]]:
    """选角失败兜底：四位通用创作者阵容（作词/作曲/制作人/乐评人）。"""
    return [
        {
            "name": "作词人",
            "field": "词作与意象",
            "persona": "重视意象与文学性",
            "icon": "✍️",
            "order": 1,
            "finalizer": False,
        },
        {
            "name": "作曲家",
            "field": "调式与和声",
            "persona": "乐理派",
            "icon": "🎼",
            "order": 2,
            "finalizer": False,
        },
        {
            "name": "制作人",
            "field": "编曲与听感",
            "persona": "务实派",
            "icon": "🎧",
            "order": 3,
            "finalizer": True,
        },
        {
            "name": "乐评人",
            "field": "挑剔听众",
            "persona": "毒舌挑剔",
            "icon": "👀",
            "order": 4,
            "finalizer": False,
        },
    ]


def pad_cast(cast_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """阵容数量不足 4 位时补位。"""
    if len(cast_list) >= 4:
        return cast_list
    return (
        cast_list
        + [
            {
                "name": f"专家{n}",
                "field": "音乐创作",
                "persona": "",
                "icon": "🎙️",
                "order": n,
                "finalizer": False,
            }
            for n in range(len(cast_list) + 1, 5)
        ]
    )[:4]


def build_agenda(
    ordered: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """对抗式议程：提案 → 反驳 → 辩护（core）；补充轮候选人（supporters，quick 模式跳过）。"""
    proposer = ordered[0] if ordered else None
    critic = next((r for r in ordered if int(r.get("order") or 99) == 4), None)
    supporters = [
        r
        for r in ordered
        if r is not proposer and r is not critic and not r.get("finalizer")
    ]
    # 核心对抗闭环：提案 → 反驳 → 辩护
    core: list[dict[str, Any]] = []
    if proposer is not None:
        core.append(
            {
                "role": proposer,
                "task": _proposer_task(),
                "stance": "你立场鲜明，敢于坚持自己的方案，不怕被质疑。",
            }
        )
    if critic is not None and proposer is not None:
        core.append(
            {
                "role": critic,
                "task": _critic_task(),
                "stance": "你默认否定，除非有具体证据；你只挑刺，不给替代方案。",
            }
        )
    if proposer is not None and critic is not None:
        core.append(
            {
                "role": proposer,
                "task": _defense_task(),
                "stance": "你敢于反驳不认同的批评，不为和谐而全盘接受。",
            }
        )
    return core, supporters


async def speak_turn(
    db: AsyncSession,
    *,
    model: str,
    theme: str,
    style: str,
    item: dict[str, Any],
    opponent_block: str,
    kb_block: str,
) -> str:
    """圆桌一轮发言：上游偶发超时/5xx 重试 2 次再放弃，避免单次抖动中断整轮讨论。"""
    role = item["role"]
    persona = (
        f"你是{role.get('name')}（{role.get('field')}）：{role.get('persona')}\n"
        f"【本轮立场】{item['stance']}"
    )
    # 自我中心投影：只给上一个对手的原话（不全文拼接，防复读套话）
    prompt = _speaker_prompt(
        theme,
        style,
        str(item["task"]),
        opponent=opponent_block,
        extra=kb_block,
    )
    resolved = await resolve_text_provider(db, model)
    last_err = ""
    for attempt in range(3):
        try:
            result = await resolved.provider.generate(  # type: ignore[attr-defined]
                prompt, resolved.model, system=persona, temperature=0.9
            )
            return _provider_text(result).strip()
        except Exception as exc:
            last_err = str(exc)[:80]
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
    return f"（{role.get('name')} 本轮发言生成失败：{last_err or '上游异常'}）"


async def followup_reply(
    db: AsyncSession, *, model: str, prompt: str, persona: str
) -> str:
    """追问轮单角色发言（原 roundtable_followup._reply）。失败不中断整场（返回占位句）。"""
    try:
        resolved = await resolve_text_provider(db, model)
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt, resolved.model, system=persona, temperature=0.9
        )
        return _provider_text(result).strip()
    except Exception as exc:
        return f"（发言中断：{str(exc)[:80]}）"


async def _with_heartbeat(
    coro_factory, event_type: str = "thinking", interval: float = 25.0
) -> AsyncIterator[dict[str, Any] | tuple[str, Any]]:
    """运行协程并在等待期间周期产出 SSE 心跳事件（防 nginx 读超时断流 → 前端 network error）。

    圆桌每轮发言/定稿是一次长时间 LLM 调用（含重试），nginx proxy_read_timeout
    只按"两次读取间隔"计——每 25 秒发一个心跳事件保持连接有数据流动，
    nginx 永不超时，前端也能实时看到「思考中」状态。

    用法：
        async for ev in _with_heartbeat(lambda: _speak(item)):
            if isinstance(ev, tuple):
                value = ev[1]  # ("result", 协程返回值)
            else:
                yield ev       # 心跳事件直接透传给前端
    """
    task = asyncio.create_task(coro_factory())
    try:
        while True:
            try:
                value = await asyncio.wait_for(asyncio.shield(task), timeout=interval)
                yield ("result", value)
                return
            except TimeoutError:
                yield {"type": event_type, "payload": "working"}
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def _extract_fix_list(db: AsyncSession, rounds: list[dict[str, str]]) -> str:
    """定稿前把「批评→替代」结构化提取，注入定稿 prompt 作为必改清单。

    失败返回空串（定稿照常进行，模型从讨论自行提取）。
    """
    transcript = _transcript_block(rounds, limit=1800)
    if not transcript or ("批评" not in transcript and "毒舌" not in transcript):
        return ""
    resolved = await resolve_text_provider(db, "")
    try:
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            _FIX_LIST_PROMPT.format(transcript=transcript[:4000]),
            resolved.model,
            temperature=0.2,
        )
        text = _provider_text(result).strip()
        import re as _re

        cleaned = _re.sub(r"^```(?:json)?\s*", "", text)
        cleaned = _re.sub(r"\s*```$", "", cleaned)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return ""
        data = json.loads(cleaned[start : end + 1])
        fixes = data.get("fixes") or []
        return "\n".join(str(f) for f in fixes if str(f).strip())[:800]
    except Exception:
        return ""


async def _produce_final(
    db: AsyncSession,
    *,
    theme: str,
    style: str,
    finalizer: dict[str, Any] | None,
    rounds: list[dict[str, str]],
    kb_block: str = "",
    rewrite_warnings: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """定稿轮：主编把关 + 结构自检。返回 (final, checks)。

    rewrite_warnings 非空时为重写轮：把上一轮自检警告注入 prompt 要求逐条修正。
    """
    finalizer_name = str((finalizer or {}).get("name") or "主理人")
    # 裁决去位置偏见：随机化发言块顺序（每个块带 speaker 名，主理人按观点质量而非顺序裁决）
    transcript = _shuffled_transcript(rounds)
    # 定稿前把「批评→替代」结构化提取（失败返回空，定稿照常）
    try:
        fix_list = await _extract_fix_list(db, rounds)
    except Exception:
        fix_list = ""
    final_prompt = _FINAL_PROMPT.format(
        name=finalizer_name,
        field=str((finalizer or {}).get("field") or "音乐制作"),
        theme=theme,
        style=style or "（自由）",
        style_profile=_style_profile_block(style) + kb_block,
        transcript=transcript,
        fix_list=fix_list
        or "（无结构化清单：从讨论记录自行提取评审点名批评过的元素与替代方案，定稿必须落实）",
    )
    if rewrite_warnings:
        final_prompt += (
            "\n\n【上一轮自检警告】（本次为修正轮：必须逐条修正下列问题后再输出定稿，"
            "修正后的作品不得再出现同类问题）\n" + "\n".join(f"- {w}" for w in rewrite_warnings)
        )
    final = await generate_json_with_retry(db, model="", prompt=final_prompt, temperature=0.7)
    if not final.get("error") and isinstance(final.get("final"), dict):
        final = final["final"]  # 兼容模型偶发输出的嵌套结构
    if not final.get("error"):
        final["lyrics"] = _repair_lyrics(str(final.get("lyrics") or ""))
    checks = [] if final.get("error") else _validate_lyrics(str(final.get("lyrics") or ""))
    return final, checks


async def _has_unresolved_conflict(
    db: AsyncSession, theme: str, rounds: list[dict[str, str]]
) -> bool:
    """共识检测（需求6：共识就停）——判断辩论是否还有未解决的实质分歧。

    辩护轮后调用：若已收敛（辩护实质回应了关键批评）→ False，跳过补充轮；
    若仍有明显对立 → True，跑补充轮。判断失败时保守返回 True（跑补充轮）。
    """
    transcript = _transcript_block(rounds, limit=1500)
    prompt = (
        f"下面是关于「{theme}」的创作讨论（提案 → 反驳 → 辩护）：\n{transcript}\n\n"
        "判断：提案与反驳之间是否还有「未解决的实质分歧」？\n"
        "- 若辩护轮已实质回应了所有关键批评（达成共识/收敛），has_conflict=false\n"
        "- 若仍有明显对立、关键问题未被回应，has_conflict=true\n"
        '严格输出 JSON（不要任何多余文字）：{"has_conflict": true} 或 {"has_conflict": false}'
    )
    try:
        resolved = await resolve_text_provider(db, "")
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt, resolved.model, temperature=0.0
        )
        data = _extract_json(_provider_text(result))
        return bool(data.get("has_conflict", False))
    except Exception:
        return True  # 判断失败保守处理：跑补充轮
