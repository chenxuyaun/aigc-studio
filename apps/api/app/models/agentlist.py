"""AgentList 外部 AI Agent 项目目录接入（agentlist.top 全量数据）。"""

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class AgentProject(Base):
    """开源 AI Agent 项目条目（1484 个）。"""

    __tablename__ = "agentlist_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    github_url: Mapped[str] = mapped_column(String(1000), default="")
    homepage_url: Mapped[str] = mapped_column(String(1000), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组
    stars: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str] = mapped_column(String(50), default="")
    license: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )


class AgentArticle(Base):
    """长文（75 篇）。"""

    __tablename__ = "agentlist_articles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[str] = mapped_column(Text, default="[]")
    related_projects: Mapped[str] = mapped_column(Text, default="[]")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())


class AgentComparison(Base):
    """PK 对比表（31 组）。"""

    __tablename__ = "agentlist_comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[str] = mapped_column(Text, default="[]")
    projects: Mapped[str] = mapped_column(Text, default="[]")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
