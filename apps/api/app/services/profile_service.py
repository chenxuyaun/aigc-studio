"""成长档案（用户偏好学习）：从创作记录聚合偏好，注入 Mission 规划与圆桌提示词。

数据来源（被动学习，不打扰用户）：
- music_works：风格 tags / 主题（创作风格倾向）
- mission_runs：目标与步骤类型分布（任务习惯）
- agent_runs：常用 Agent（协作偏好）
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

_PROFILE_PROMPT = """你是用户研究分析师。根据用户的创作数据，总结「用户创作画像」。
规则：2-4 句话：创作风格倾向 + 主题偏好 + 协作习惯；口语化；不超过 120 字。
输出 JSON（不要任何多余文字）：{{"profile": "…"}}

用户数据：
{data}"""


async def aggregate_preferences(db: AsyncSession, user_id: str) -> dict[str, Any]:
    """聚合用户偏好（风格 top3 / 主题词 top5 / 常用 Agent top3 / 常用步骤类型）。"""
    from sqlalchemy import select

    from app.models.agent import Agent
    from app.models.agent_run import AgentRun
    from app.models.mission_run import MissionRun
    from app.models.music_work import MusicWork

    styles: Counter[str] = Counter()
    themes: Counter[str] = Counter()
    steps: Counter[str] = Counter()
    agent_ids: Counter[str] = Counter()

    works = (
        await db.execute(
            select(MusicWork).where(MusicWork.user_id == user_id).limit(100)
        )
    ).scalars().all()
    for w in works:
        if w.style:
            styles[str(w.style)] += 1
        for t in (str(w.tags or "").split(",")):
            t = t.strip()
            if t and t != w.style:
                themes[t] += 1
        if w.theme:
            for word in str(w.theme)[:60]:
                pass  # 主题词频依赖分词，跳过细粒度（用 tags 足够）

    runs = (
        await db.execute(
            select(MissionRun).where(MissionRun.user_id == user_id).limit(50)
        )
    ).scalars().all()
    for r in runs:
        try:
            plan = json.loads(r.plan or "[]")
            for s in plan:
                steps[str(s.get("kind") or "")] += 1
        except Exception:
            pass

    agent_runs = (
        await db.execute(
            select(AgentRun).where(AgentRun.user_id == user_id).limit(50)
        )
    ).scalars().all()
    for a in agent_runs:
        agent_ids[str(a.agent_id)] += 1

    agent_names: dict[str, str] = {}
    if agent_ids:
        rows = (
            await db.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_(list(agent_ids)))
            )
        ).all()
        agent_names = {str(i): str(n) for i, n in rows}

    return {
        "styles": [s for s, _ in styles.most_common(3)],
        "themes": [t for t, _ in themes.most_common(5)],
        "steps": [s for s, _ in steps.most_common(5)],
        "agents": [
            {"id": aid, "name": agent_names.get(aid, aid[:8])}
            for aid, _ in agent_ids.most_common(3)
        ],
    }


async def build_profile_text(db: AsyncSession, user_id: str) -> str:
    """偏好 → 注入文本（【用户偏好】块；无数据返回空串）。"""
    prefs = await aggregate_preferences(db, user_id)
    lines: list[str] = []
    if prefs["styles"]:
        lines.append("风格倾向：" + "、".join(prefs["styles"]))
    if prefs["themes"]:
        lines.append("主题偏好：" + "、".join(prefs["themes"]))
    if prefs["agents"]:
        lines.append(
            "常用 Agent：" + "、".join(a["name"] for a in prefs["agents"])
        )
    if prefs["steps"]:
        lines.append("常用任务类型：" + "、".join(prefs["steps"]))
    if not lines:
        return ""
    return "【用户偏好】（用户创作历史中体现的偏好，规划与创作时优先贴合）\n" + "\n".join(lines)


async def summarize_profile(db: AsyncSession, user_id: str) -> str:
    """LLM 一句话画像（失败返回空）。"""
    prefs = await aggregate_preferences(db, user_id)
    if not any(prefs.values()):
        return ""
    from app.services.provider_resolver import resolve_text_provider

    data = json.dumps(prefs, ensure_ascii=False)
    try:
        resolved = await resolve_text_provider(db, "")
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            _PROFILE_PROMPT.format(data=data[:1200]), resolved.model, temperature=0.4
        )
        from app.services.text_utils import extract_json, result_text

        return str(extract_json(result_text(result)).get("profile") or "").strip()
    except Exception:
        return ""
