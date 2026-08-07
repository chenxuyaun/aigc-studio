"""Story Crew 创作团队：多 agent 流水线。

预置创作角色（各带独立 system 角色定位）：
- director（主编）：审阅 bible 与已写章节，输出下一章剧情方向（存 settings["direction"]）
- writer（作家）：按方向生成章节（复用 story_forge.generate_chapter）
- editor（校对）：检查设定一致性/伏笔/文风，输出审校报告（存章节 notes["review"]）
- stagehand（剧务）：读最新章节，更新各角色 current_state（角色弧线推进）

每个阶段 = 1 次 LLM 调用 + 结构化落库；后续可扩展为带 MCP 工具循环的 agent。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import roleplay, story_forge
from app.services.provider_resolver import resolve_text_provider

_STAGE_PROMPTS: dict[str, str] = {
    "director": (
        "你是这部小说的主编。基于故事梗概、角色设定、已写章节与前情摘要，"
        "规划下一章的剧情走向。输出：1) 本章核心冲突/事件（2-3 句）"
        "2) 涉及的角色及各自的表现要点。直接输出指令文本，不要寒暄。"
    ),
    "editor": (
        "你是这部小说的校对编辑。审阅指定章节正文，对照角色设定与世界设定，"
        "检查：人物行为是否与性格/状态一致、是否有设定矛盾、伏笔是否照应、文风是否统一。"
        "输出审校报告（问题清单 + 修改建议），没有问题时说明「通过」。"
    ),
    "stagehand": (
        "你是这部小说的剧务。阅读最新章节正文，推断每位在场角色的当前状态"
        "（处境、心情、关系变化、目标进展）。"
        "只输出 JSON 对象 {\"角色名\": \"状态描述\"}，不要输出其他文字。"
    ),
    "consistency": (
        "你是这部小说的全书一致性审查员。阅读全书已完成章节与角色设定，"
        "系统检查四类问题并输出结构化报告：\n"
        "1. 角色一致性：同一角色的称呼/身份/性格在不同章节是否矛盾；"
        "2. 时间线：章节间的时间引用（日期/时刻/先后顺序）是否自洽；"
        "3. 事实与物品：关键物品/证据/地点的描述是否前后一致，是否被提及后未回收；"
        "4. 伏笔与设定：伏笔是否照应，设定是否与角色卡冲突。\n"
        "输出格式：先列「✅ 通过项」，再列「⚠️ 问题清单」（每条注明章节号与具体矛盾），"
        "最后给「🔧 修改建议」。没有问题时明确说「全书一致，无问题」；"
        "不得编造问题——不确定的写「待确认」并给出依据。"
    ),
}


async def run_crew(
    db: AsyncSession,
    user_id: str,
    project_id: str,
    stage: str,
    *,
    chapter_id: str | None = None,
    model: str = "",
) -> dict[str, Any]:
    """执行一个创作团队阶段。stage ∈ director / writer / editor / stagehand。"""
    project = await story_forge.get_project(db, user_id, project_id)
    if project is None:
        return {"error": "项目不存在"}
    if stage not in _STAGE_PROMPTS:
        return {"error": f"未知阶段: {stage}"}

    cards = await roleplay._load_cards(
        db, user_id, story_forge._load_json(project.character_asset_ids, [])
    )
    bible = await story_forge._bible_text(db, user_id, project, cards)
    chapters = await story_forge.list_chapters(db, user_id, project_id)
    done = [c for c in chapters if c["status"] == "done"]
    summary = story_forge._project_summary(project)
    settings = story_forge._load_json(project.settings, {})

    # ---- writer：直接走章节生成 ----
    if stage == "writer":
        if not chapter_id:
            return {"error": "writer 阶段需要 chapter_id"}
        direction = str(settings.get("direction") or "")
        result = await story_forge.generate_chapter(
            db, user_id, project_id, chapter_id, model=model, instruction=direction
        )
        return {**result, "stage": "writer"}

    # ---- director：剧情方向 ----
    if stage == "director":
        system_prompt = _STAGE_PROMPTS["director"] + (
            f"\n【故事梗概】\n{project.synopsis}"
            f"\n【角色设定】\n{bible}"
            f"\n【已写章节】\n"
            + "\n".join(f"第{c['chapter_no']}章《{c['title']}》：{c['outline']}" for c in chapters)
            + (f"\n【前情摘要】\n{summary}" if summary else "")
        )
        content = await _ask(db, system_prompt, model)
        if "error" in content:
            return content
        settings["direction"] = content["text"]
        updated = await story_forge.update_project(
            db, user_id, project_id, {"settings": settings}
        )
        return {"stage": "director", "direction": content["text"], "ok": updated is not None}

    # ---- editor：审校报告 ----
    if stage == "editor":
        if not chapter_id:
            return {"error": "editor 阶段需要 chapter_id"}
        chapter = await story_forge.get_chapter(db, user_id, chapter_id)
        if chapter is None:
            return {"error": "章节不存在"}
        system_prompt = (
            _STAGE_PROMPTS["editor"]
            + f"\n【角色设定】\n{bible}"
            + f"\n【指定章节《{chapter.title}》】\n{chapter.content}"
        )
        content = await _ask(db, system_prompt, model)
        if "error" in content:
            return content
        notes = story_forge._load_json(chapter.notes, {})
        notes["review"] = content["text"]
        await story_forge.update_chapter(db, user_id, chapter_id, {"notes": notes})
        return {"stage": "editor", "review": content["text"], "ok": True}

    # ---- stagehand：角色状态推进 ----
    if stage == "stagehand":
        if not done:
            return {"error": "还没有已完成的章节，请先生成章节"}
        latest = done[-1]
        system_prompt = (
            _STAGE_PROMPTS["stagehand"]
            + f"\n【角色设定】\n{bible}"
            + f"\n【最新章节《{latest['title']}】\n{latest['content'][:4000]}"
        )
        content = await _ask(db, system_prompt, model)
        if "error" in content:
            return content
        states = _parse_states(content["text"])
        states_updated: list[dict[str, Any]] = []
        for s in await story_forge.list_story_characters(db, user_id, project_id):
            state = states.get(s["name"]) or states.get(s["name"].lstrip("「」"))
            if state and state != s["current_state"]:
                await story_forge.update_story_character(
                    db, user_id, s["id"], {"current_state": state}
                )
                states_updated.append({"character": s["name"], "current_state": state})
        return {"stage": "stagehand", "states": states_updated, "ok": True}

    # ---- consistency：全书一致性审查 ----
    if stage == "consistency":
        if not done:
            return {"error": "还没有已完成的章节，请先生成章节"}
        # 全书正文（截断保护：最多 6 万字）
        body = "\n\n".join(
            f"===== 第{c['chapter_no']}章《{c['title']}》 =====\n{c['content']}"
            for c in done
        )[:60000]
        system_prompt = (
            _STAGE_PROMPTS["consistency"]
            + f"\n【角色设定】\n{bible}"
            + f"\n【全书正文（{len(done)} 章）】\n{body}"
        )
        content = await _ask(db, system_prompt, model, max_tokens=2048)
        if "error" in content:
            return content
        # 报告存项目 settings（可反复查看）
        settings["consistency_report"] = content["text"]
        await story_forge.update_project(db, user_id, project_id, {"settings": settings})
        return {"stage": "consistency", "report": content["text"], "ok": True}

    return {"error": "未知阶段"}


async def _ask(
    db: AsyncSession, system_prompt: str, model: str, max_tokens: int = 1024
) -> dict[str, Any]:
    """单次 LLM 调用（真实 provider，失败报错不降级）。"""
    resolved = await resolve_text_provider(db, model)
    provider = roleplay.cast_text_provider(resolved.provider)
    try:
        result = await provider.generate(system_prompt, resolved.model, max_tokens=max_tokens)
    except Exception as exc:
        return {"error": f"生成失败：{str(exc)[:200]}"}
    text = (result.content or "").strip()
    if not text:
        return {"error": "模型未返回内容"}
    return {"text": text, "model": resolved.model}


def _parse_states(raw: str) -> dict[str, str]:
    """宽容解析角色状态 JSON：取第一个 { ... } 对象；失败返回 {}。"""
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, (str, int, float))}
