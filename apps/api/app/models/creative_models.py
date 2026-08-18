"""创作智能内核存储模型（P0 数据基座，docs/creative-engine/05/10）。

- StoryState: 每项目一份当前故事状态（world/timeline/causal_graph/open_loops/...）
- StoryStateSnapshot: 每章状态快照（可回滚，与 story_chapter_versions 联动）
- CreativeRun: 创作流水线审计（每次 PROPOSE/ACCEPT/REJECT/生成 + 成本）
- CreativePrompt: Prompt 版本化（prompt_key → 版本号 → 内容，可回滚）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class StoryStateRow(Base):
    __tablename__ = "story_states"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # JSON 字符串：StoryState（app/creative/schemas.py::StoryState）
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_chapter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), onupdate=func.now()
    )


class StoryStateSnapshot(Base):
    __tablename__ = "story_state_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())


class CreativeRun(Base):
    """创作流水线审计（10 §3）：每步 Agent 动作留痕。"""

    __tablename__ = "creative_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False, default="chapter")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    agent_role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(16), nullable=False, default="GENERATE")
    # JSON 字符串：判定/提案（verdict/delta 摘要）
    verdict_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())


class CreativePrompt(Base):
    """Prompt 版本化（10 §4）：prompt_key 指向版本号，出问题一键回滚。"""

    __tablename__ = "creative_prompts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    prompt_key: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), server_default=func.now())
