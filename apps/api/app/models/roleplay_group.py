"""多人创作群：群资料（邀请码）+ 成员关系。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RoleplayGroup(Base):
    """群（对应一个多人房间会话 roleplay_chats.is_room=True）。"""

    __tablename__ = "roleplay_groups"

    chat_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    description: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    invite_code: Mapped[str] = mapped_column(
        String(12), nullable=False, index=True, unique=True,
        default=lambda: uuid.uuid4().hex[:8],
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )


class RoleplayGroupMember(Base):
    """群成员（复合主键 group_id+user_id）。"""

    __tablename__ = "roleplay_group_members"

    group_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # owner / member
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member", server_default="member"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )
