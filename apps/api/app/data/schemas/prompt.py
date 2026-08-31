from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator


class PromptCreate(BaseModel):
    title: str
    content: str
    category_id: str | None = None
    prompt_type: str = "text"
    is_public: bool = True
    tag_ids: list[str] | None = None
    # 标签名称列表：后端按名称 upsert，与 tag_ids 二选一（前端用名称更友好）
    tags: list[str] | None = None


class PromptUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    category_id: str | None = None
    prompt_type: str | None = None
    is_public: bool | None = None
    tags: list[str] | None = None


class PromptResponse(BaseModel):
    id: str
    title: str
    content: str
    category_id: str | None
    prompt_type: str
    is_public: bool
    favorite_count: int
    use_count: int
    author_id: str
    source_type: str
    cover_url: str = ""
    source_url: str = ""
    source_author: str = ""
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("tags", mode="before")
    @classmethod
    def _tags_to_names(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, (list, tuple)):
            return []
        names = [t.name if hasattr(t, "name") else str(t) for t in v]
        return sorted(set(names))
