"""Creative State 持久化层（P0）：StoryState / Constitution 的落库读写。

- get_story_state / save_story_state / snapshot_story_state：StoryState ↔ story_states 表
- get_constitution / save_constitution：CharacterConstitution ↔ story_characters.constitution

宽容策略：JSON 损坏/缺列时返回 None（不阻断 legacy 路径，与 get_constitution 一致）。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.creative.schemas import CharacterConstitution, StoryState
from app.models.creative_models import (
    StoryStateRow,
    StoryStateSnapshot,
)
from app.models.story_character import StoryCharacter


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


# ============================================================
# StoryState
# ============================================================


async def get_story_state(db: AsyncSession, project_id: str, user_id: str) -> StoryState | None:
    """读取项目当前 StoryState；无记录或 JSON 损坏返回 None（调用方建新状态）。"""
    row = (
        await db.execute(
            select(StoryStateRow).where(
                StoryStateRow.project_id == project_id,
                StoryStateRow.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    data = _load_json(row.state_json, None)
    if not isinstance(data, dict):
        return None
    try:
        state = StoryState.model_validate(data)
    except Exception:
        return None
    state.project_id = project_id
    return state


async def save_story_state(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    state: StoryState,
    *,
    chapter_no: int = 0,
) -> StoryStateRow:
    """保存 StoryState（upsert 单行）。返回行对象（调用方 commit）。"""
    row = (
        await db.execute(
            select(StoryStateRow).where(
                StoryStateRow.project_id == project_id,
                StoryStateRow.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    state_json = state.model_dump_json()
    if row is None:
        row = StoryStateRow(
            project_id=project_id,
            user_id=user_id,
            version=state.version,
            state_json=state_json,
            updated_chapter=chapter_no,
        )
        db.add(row)
    else:
        row.version = state.version
        row.state_json = state_json
        row.updated_chapter = chapter_no
    return row


async def snapshot_story_state(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    state: StoryState,
    *,
    chapter_no: int = 0,
) -> StoryStateSnapshot:
    """每章状态快照（05 §6）：与 story_chapter_versions 联动回滚。"""
    snap = StoryStateSnapshot(
        id=str(uuid.uuid4()),
        project_id=project_id,
        user_id=user_id,
        chapter_no=chapter_no,
        version=state.version,
        state_json=state.model_dump_json(),
    )
    db.add(snap)
    return snap


# ============================================================
# CharacterConstitution
# ============================================================


async def get_constitution(
    db: AsyncSession, character_id: str
) -> CharacterConstitution | None:
    """读取角色 Constitution；未建模/损坏返回 None（legacy 行为）。"""
    row = await db.get(StoryCharacter, character_id)
    if row is None:
        return None
    data = _load_json(row.constitution, None)
    if not isinstance(data, dict) or not data:
        return None
    try:
        return CharacterConstitution.model_validate(data)
    except Exception:
        return None


async def save_constitution(
    db: AsyncSession, character_id: str, constitution: CharacterConstitution
) -> bool:
    """保存角色 Constitution（覆盖写）。返回是否成功（调用方 commit）。"""
    row = await db.get(StoryCharacter, character_id)
    if row is None:
        return False
    row.constitution = constitution.model_dump_json()
    return True


def constitution_to_bible_block(constitution: CharacterConstitution, name: str) -> str:
    """Constitution → bible 注入文本（04 §6：_build_chapter_prompt 的【价值层级】段）。

    供 P3 接入 _bible_text；本函数保证注入内容的结构化与克制（不倾倒全部 22 字段）。
    """
    lines = [f"【角色「{name}」· 决策模型】"]
    if constitution.worldview:
        lines.append(f"世界观：{constitution.worldview}")
    if constitution.value_hierarchy:
        order = sorted(
            constitution.value_hierarchy.items(), key=lambda kv: -kv[1]
        )
        lines.append("价值层级：" + " > ".join(f"{k}({v:.2f})" for k, v in order))
    if constitution.mission:
        lines.append(f"使命：{constitution.mission}")
    if constitution.decision_rules:
        rules = "; ".join(
            f"若{r.condition}→{r.action}" for r in constitution.decision_rules[:5]
        )
        lines.append(f"决策规则：{rules}")
    if constitution.moral_limits:
        lines.append("道德底线：" + "；".join(constitution.moral_limits[:5]))
    if constitution.emotional_triggers:
        lines.append(
            "情绪触发器（仅影响即时反应，不决定重大行为）："
            + "、".join(constitution.emotional_triggers[:5])
        )
    return "\n".join(lines)
