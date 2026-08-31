from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    graph: dict[str, object]
    category_id: str | None = None
    workflow_type: str = "sequential"
    is_public: bool = True


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    graph: dict[str, object] | None = None
    category_id: str | None = None
    workflow_type: str | None = None
    is_public: bool | None = None


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str
    graph: dict[str, object]
    workflow_type: str
    is_public: bool
    favorite_count: int
    use_count: int
    author_id: str
    source_type: str
    cover_url: str = ""
    source_url: str = ""
    source_author: str = ""
    version: int = 1
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
