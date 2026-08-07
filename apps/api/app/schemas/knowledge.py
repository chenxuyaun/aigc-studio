from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)


class KnowledgeDocumentSummary(BaseModel):
    id: str
    title: str
    char_count: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class KnowledgeDocumentDetail(KnowledgeDocumentSummary):
    content: str


class KnowledgeAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    model: str = ""
    # 可选：限定在指定文档内检索；不传则检索全部个人文档
    doc_ids: list[str] | None = None
    max_chunks: int = Field(default=3, ge=1, le=6)
