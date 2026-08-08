"""群服务：建群/详情/邀请加入/踢人/改资料（多人创作完整群）。"""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roleplay_group import RoleplayGroup, RoleplayGroupMember


async def create_group(
    db: AsyncSession,
    *,
    owner_id: str,
    chat_id: str,
    name: str,
    description: str,
) -> RoleplayGroup:
    """建群（调用方需已创建 is_room 会话）。"""
    group = RoleplayGroup(
        chat_id=chat_id,
        owner_id=owner_id,
        name=name or "未命名群",
        description=description or "",
        invite_code=secrets.token_hex(4),  # 8 位邀请码
    )
    db.add(group)
    db.add(RoleplayGroupMember(group_id=chat_id, user_id=owner_id, role="owner"))
    await db.flush()
    return group


async def get_group(db: AsyncSession, chat_id: str) -> RoleplayGroup | None:
    return (
        await db.execute(select(RoleplayGroup).where(RoleplayGroup.chat_id == chat_id))
    ).scalar_one_or_none()


async def list_members(db: AsyncSession, chat_id: str) -> list[RoleplayGroupMember]:
    rows = await db.execute(
        select(RoleplayGroupMember).where(RoleplayGroupMember.group_id == chat_id)
    )
    return list(rows.scalars().all())


async def is_member(db: AsyncSession, chat_id: str, user_id: str) -> bool:
    row = (
        await db.execute(
            select(RoleplayGroupMember).where(
                RoleplayGroupMember.group_id == chat_id,
                RoleplayGroupMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def join_by_code(
    db: AsyncSession, invite_code: str, user_id: str
) -> tuple[RoleplayGroup | None, str]:
    """邀请码加入：返回 (group, error)。"""
    group = (
        await db.execute(
            select(RoleplayGroup).where(RoleplayGroup.invite_code == invite_code)
        )
    ).scalar_one_or_none()
    if group is None:
        return None, "邀请码无效"
    if await is_member(db, group.chat_id, user_id):
        return group, ""
    db.add(RoleplayGroupMember(group_id=group.chat_id, user_id=user_id, role="member"))
    await db.flush()
    return group, ""


async def remove_member(
    db: AsyncSession, chat_id: str, user_id: str, *, actor_id: str
) -> tuple[bool, str]:
    """踢人（群主或本人退出）。返回 (ok, error)。"""
    group = await get_group(db, chat_id)
    if group is None:
        return False, "群不存在"
    if group.owner_id != actor_id and user_id != actor_id:
        return False, "仅群主可移除成员"
    if group.owner_id == user_id:
        return False, "群主不可退出，请先转让"
    await db.execute(
        delete(RoleplayGroupMember).where(
            RoleplayGroupMember.group_id == chat_id,
            RoleplayGroupMember.user_id == user_id,
        )
    )
    await db.flush()
    return True, ""


async def update_group(
    db: AsyncSession,
    chat_id: str,
    *,
    actor_id: str,
    name: str | None = None,
    description: str | None = None,
    reset_invite: bool = False,
) -> tuple[RoleplayGroup | None, str]:
    group = await get_group(db, chat_id)
    if group is None:
        return None, "群不存在"
    if group.owner_id != actor_id:
        return None, "仅群主可修改群资料"
    if name is not None:
        group.name = name[:100]
    if description is not None:
        group.description = description[:500]
    if reset_invite:
        group.invite_code = secrets.token_hex(4)
    await db.flush()
    return group, ""


def group_dict(
    group: RoleplayGroup,
    members: list[RoleplayGroupMember],
    usernames: dict[str, str],
) -> dict[str, Any]:
    return {
        "chat_id": group.chat_id,
        "name": group.name,
        "description": group.description,
        "invite_code": group.invite_code,
        "owner_id": group.owner_id,
        "members": [
            {
                "user_id": m.user_id,
                "username": usernames.get(m.user_id, m.user_id[:8]),
                "role": m.role,
            }
            for m in members
        ],
    }
