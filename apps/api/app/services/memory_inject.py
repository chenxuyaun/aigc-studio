"""角色陪伴记忆注入：原著档案 + 交互记忆（L0-L3）组装 prompt 片段。

召回策略（上层把握"情商"与大方向，下层补充"细节证据"与精确度）：
- system 稳定注入（每轮都有）：原著核心档案（角色是谁/怎么说话，恒常）
  → L3 交互画像（用户偏好/关系进展）→ L2 场景导航（当前可能情境，heat 排序）
- user 动态注入（按当前语句检索）：L1 原子事实（细节证据）+ 原著事实库（书中相关事件）
- 预算：总注入 ≤ 角色卡 settings.memory.budget（默认 2500 字符），system 优先；
- 降级：gateway 不可用/超时（3s）→ 返回空串，对话完全不受影响。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character_profile import CharacterProfile
from app.models.roleplay_character import RoleplayCharacter
from app.services import memory_client
from app.services.knowledge_retrieval import retrieve

# gateway 召回总超时（秒）：超时静默降级，不拖慢对话
_RECALL_TIMEOUT = 3.0

# 各段字符上限（system 优先分配）
_PROFILE_MAX = 800
_PERSONA_MAX = 1500
_SCENARIO_MAX = 500
_ATOM_MAX_CHARS = 200
_BOOK_HIT_MAX_CHARS = 300


def _load_json(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except Exception:
        return default


async def memory_config(db: AsyncSession, user_id: str, asset_id: str) -> dict[str, Any]:
    """角色卡 settings.memory 注入配置（默认开启，预算 2500）。"""
    row = await db.get(RoleplayCharacter, asset_id)
    if row is None or row.user_id != user_id:
        return {"inject": False, "budget": 2500}
    settings = _load_json(row.settings, {})
    cfg = (settings.get("memory") or {}) if isinstance(settings, dict) else {}
    return {
        "inject": bool(cfg.get("inject", True)),
        "budget": int(cfg.get("budget", 2500)),
    }


def _profile_core(profile: CharacterProfile) -> str:
    """原著档案恒常片段（身份/性格/说话风格）。"""
    parts = []
    if profile.identity:
        parts.append(f"身份：{profile.identity}")
    if profile.personality:
        parts.append(f"性格：{profile.personality}")
    if profile.speech_style:
        parts.append(f"说话风格：{profile.speech_style}")
    core = "\n".join(parts).strip()
    return core[:_PROFILE_MAX]


async def _search_book_chunks(
    profile: CharacterProfile | None, query: str, top_k: int = 2
) -> list[str]:
    """原著分块事实库关键词检索（复用 knowledge_retrieval.retrieve）。"""
    if profile is None or not query:
        return []
    chunks = _load_json(profile.book_chunks, [])
    if not chunks:
        return []
    hits = retrieve(
        [(str(c.get("idx")), str(c.get("title") or ""), str(c.get("text") or "")) for c in chunks],
        query,
        top_k=top_k,
        min_score=1,
    )
    return [text[:_BOOK_HIT_MAX_CHARS] for _, _, text, _ in hits]


def _format_atom(a: dict[str, Any]) -> str:
    kind = a.get("type") or "fact"
    scene = a.get("scene_name") or ""
    prefix = f"[{kind}|{scene}]" if scene else f"[{kind}]"
    content = str(a.get("content") or "")[:_ATOM_MAX_CHARS]
    return f"- {prefix} {content}"


def _scenario_nav(scenarios: list[dict[str, Any]], max_items: int = 5) -> str:
    """场景导航：按 heat 降序取前 N 个（name + summary）。"""
    items = []
    for s in sorted(scenarios, key=lambda x: -int(x.get("heat") or 0))[:max_items]:
        name = s.get("name") or s.get("path") or "场景"
        summary = str(s.get("summary") or "")[:80]
        items.append(f"- {name}：{summary}" if summary else f"- {name}")
    return "\n".join(items)


async def build_memory_injection(
    db: AsyncSession, user_id: str, asset_id: str, user_query: str
) -> tuple[str, str]:
    """返回 (system_extra, user_extra)；配置关闭/异常时 ("", "")。"""
    cfg = await memory_config(db, user_id, asset_id)
    if not cfg["inject"] or not asset_id:
        return "", ""
    budget = max(500, int(cfg["budget"]))

    # ── 原著档案（恒常）──
    profile = (
        await db.execute(
            select(CharacterProfile).where(
                CharacterProfile.asset_id == asset_id,
                CharacterProfile.user_id == user_id,
                CharacterProfile.status == "done",
            )
        )
    ).scalar_one_or_none()

    # ── 交互记忆（gateway，并行 + 超时降级）──
    async def _safe(coro: Any) -> Any:
        try:
            return await asyncio.wait_for(coro, timeout=_RECALL_TIMEOUT)
        except Exception:
            return None

    if profile is not None and user_query:
        book_task: Any = _safe(_search_book_chunks(profile, user_query))
    else:
        book_task = _safe(asyncio.sleep(0))
    if user_query:
        atom_task: Any = _safe(
            memory_client.memory_search_atomic(user_id, asset_id, user_query, limit=4)
        )
    else:
        atom_task = _safe(asyncio.sleep(0))

    persona, scenarios, atoms, book_hits = await asyncio.gather(
        _safe(memory_client.memory_read_core(user_id, asset_id)),
        _safe(memory_client.memory_list_scenarios(user_id, asset_id)),
        atom_task,
        book_task,
    )

    # FTS 中文单字切分可能漏召回（词典外词）：检索空时兜底拉最近原子记忆
    if not atoms:
        atoms = await _safe(memory_client.memory_query_atomic(user_id, asset_id, limit=3)) or []

    # ── system 部分（稳定注入：情商与大方向）──
    system_parts: list[str] = []
    if profile is not None:
        core = _profile_core(profile)
        if core:
            title = profile.book_title or "原著"
            system_parts.append(f"【原著档案】（你来自《{title}》，以下是你核心设定）\n{core}")
    if persona:
        system_parts.append(
            f"【交互画像】（你对他/她的了解，随时间积累）\n{str(persona)[:_PERSONA_MAX]}"
        )
    if scenarios:
        nav = _scenario_nav(scenarios)
        if nav:
            system_parts.append(f"【场景导航】（你们之间可能正在进行的场景）\n{nav}")

    # ── user 部分（动态检索：细节证据与精确度）──
    user_parts: list[str] = []
    if atoms:
        lines = "\n".join(_format_atom(a) for a in atoms if a.get("content"))
        if lines:
            user_parts.append(
                "【相关记忆】（来自你们此前的互动，可参考；若与当前对话冲突以当前为准）\n" + lines
            )
    if book_hits:
        lines = "\n\n".join(f"- {t}" for t in book_hits)
        if lines:
            title = (profile.book_title if profile else "") or "原著"
            user_parts.append(f"【原著记忆】（来自《{title}》，与当前话题相关）\n{lines}")

    # ── 预算分配：system 优先，剩余给 user ──
    system_text = "\n\n".join(system_parts)
    remaining = max(0, budget - len(system_text))
    user_text = ""
    if remaining > 120:
        user_text = "\n\n".join(user_parts)[:remaining]
    return system_text, user_text
