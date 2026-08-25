"""Agent 团队协作服务（批10）。

流程：规划（LLM 出 3-4 人分工 JSON）→ 成员串行接力（每人结合前序产出
完成自己的任务，每步即时落库供前端轮询）→ 汇总最终报告。
全程失败静默标记 failed，不抛出到请求上下文。
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_run import TeamRun
from app.services.provider_resolver import resolve_text_provider

logger = logging.getLogger("aigc.team")

_MAX_MEMBERS = 5

_PLAN_PROMPT = """你是 Agent 团队的规划者。目标：{goal}

请设计一支 {n} 人以内的创作团队，**只输出 JSON**：
{{
  "members": [
    {{"name": "成员名(中文,≤6字)", "role": "职责一句话", "task": "这个成员具体要做什么(≤60字)"}}
  ]
}}
要求：3-4 名成员；职责互不重叠、按执行顺序排列（先策划后执行再审校）；不要输出多余文字。"""

_MEMBER_PROMPT = """你是一支创作团队中的「{name}」，职责：{role}
你的任务：{task}
团队总目标：{goal}

{prev}

请直接输出你的工作成果（不要寒暄、不要复述任务）。"""

_SUMMARY_PROMPT = """你是团队队长。团队目标：{goal}

各成员产出：
{steps}

请写一份最终交付报告：先给可直接使用/发布的成果主体，再用 2-3 句话说明团队协作过程。用中文。"""


async def start_team_run(db: AsyncSession, user_id: str, goal: str) -> TeamRun:
    row = TeamRun(user_id=user_id, goal=goal.strip()[:1000])
    db.add(row)
    await db.commit()
    return row


async def run_team_bg(run_id: str) -> None:
    """后台执行入口：自开 session（HTTP 请求结束后原 session 已关闭）。"""
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as s:
            await execute_team_run(s, run_id)
    except Exception:  # noqa: BLE001 — 后台失败只落库不外抛
        logger.warning("team_run_crashed", exc_info=True, extra={"run_id": run_id})
        try:
            async with AsyncSessionLocal() as s:
                row = await _get(s, run_id)
                if row and row.status not in ("done",):
                    row.status = "failed"
                    row.error = (row.error or "") + " 执行异常中断"
                    await s.commit()
        except Exception:  # noqa: BLE001
            pass


async def execute_team_run(db: AsyncSession, run_id: str) -> None:
    row = await _get(db, run_id)
    if not row or row.status not in ("planning", "failed"):
        return
    try:
        # ── 规划 ──
        plan_raw = await _llm(
            db,
            _PLAN_PROMPT.format(goal=row.goal, n=4),
        )
        members = _parse_members(plan_raw)
        if not members:
            raise ValueError(f"规划解析失败：{plan_raw[:120]}")
        row.members = members
        row.status = "running"
        await db.commit()

        # ── 接力执行 ──
        steps: list[dict[str, str]] = []
        for m in members:
            prev_text = ""
            if steps:
                prev_text = "已完成的前序产出：\n" + "\n\n".join(
                    f"[{s['name']}·{s['role']}]\n{s['output'][:1200]}" for s in steps[-2:]
                )
            out = await _llm(
                db,
                _MEMBER_PROMPT.format(
                    name=m["name"], role=m["role"], task=m["task"], goal=row.goal, prev=prev_text
                ),
            )
            steps.append({"name": m["name"], "role": m["role"], "output": out[:4000]})
            row.steps = list(steps)  # 每步落库，前端轮询可见
            await db.commit()

        # ── 汇总 ──
        steps_text = "\n\n".join(
            f"【{s['name']} · {s['role']}】\n{s['output'][:1500]}" for s in steps
        )
        report = await _llm(db, _SUMMARY_PROMPT.format(goal=row.goal, steps=steps_text))
        row.final_report = report[:8000]
        row.status = "done"
        await db.commit()
        logger.info("team_done", extra={"run_id": run_id, "members": len(members)})
    except Exception as exc:  # noqa: BLE001 — 单次运行失败落库
        row.status = "failed"
        row.error = str(exc)[:480] or type(exc).__name__
        await db.commit()
        logger.warning("team_failed", extra={"run_id": run_id})


async def get_run(db: AsyncSession, user_id: str, run_id: str) -> TeamRun | None:
    row = await _get(db, run_id)
    if not row or row.user_id != user_id:
        return None
    return row


async def list_runs(db: AsyncSession, user_id: str, limit: int = 20) -> list[TeamRun]:
    rows = (
        (
            await db.execute(
                select(TeamRun)
                .where(TeamRun.user_id == user_id)
                .order_by(TeamRun.created_at.desc(), TeamRun.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _get(db: AsyncSession, run_id: str) -> TeamRun | None:
    return (await db.execute(select(TeamRun).where(TeamRun.id == run_id))).scalar_one_or_none()


def _parse_members(raw: str) -> list[dict[str, str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    members = []
    for m in (obj.get("members") or [])[:_MAX_MEMBERS]:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()[:12]
        role = str(m.get("role") or "").strip()[:80]
        task = str(m.get("task") or "").strip()[:120]
        if name and task:
            members.append({"name": name, "role": role or "团队成员", "task": task})
    return members


async def _llm(db: AsyncSession, prompt: str) -> str:
    resolved = await resolve_text_provider(db, "")
    # 🔴 不压 max_tokens：gpt-oss 推理模型先"思考"再作答（reasoning 可达数千
    # token），限制小了 content 直接为空；团队是后台任务慢点无妨。
    # 上游偶发限流/空响应 → 温和重试一轮（20s/40s 退避）。
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            result = await resolved.provider.generate(prompt, resolved.model)
            text = (result.content or "").strip()
            if text:
                return text
            last_err = ValueError("上游返回空内容")
        except Exception as exc:  # noqa: BLE001 — 429/超时/断流统一退避
            last_err = exc
        import asyncio

        await asyncio.sleep(20 * (attempt + 1))
    raise last_err or RuntimeError("LLM 调用失败")
