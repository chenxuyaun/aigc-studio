from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SkillCreate(BaseModel):
    name: str
    description: str = ""
    instructions: str
    skill_type: str = "tool"
    model: str = ""
    is_public: bool = True
    inputs_schema: dict[str, object] | None = None


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    skill_type: str | None = None
    model: str | None = None
    is_public: bool | None = None
    inputs_schema: dict[str, object] | None = None


class SkillResponse(BaseModel):
    id: str
    name: str
    description: str
    instructions: str
    skill_type: str
    model: str = ""
    is_public: bool
    favorite_count: int
    use_count: int
    author_id: str
    source_type: str
    cover_url: str = ""
    source_url: str = ""
    source_author: str = ""
    inputs_schema: dict[str, object] = {}
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
