from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    system_prompt: str
    category_id: str | None = None
    agent_type: str = "generic"
    is_public: bool = True
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[str] | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    category_id: str | None = None
    agent_type: str | None = None
    is_public: bool | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[str] | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    description: str
    system_prompt: str
    category_id: str | None
    agent_type: str
    is_public: bool
    favorite_count: int
    use_count: int
    author_id: str
    source_type: str
    cover_url: str = ""
    source_url: str = ""
    source_author: str = ""
    model: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[str] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
