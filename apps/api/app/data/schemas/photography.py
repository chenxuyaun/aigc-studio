from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AlbumCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    style_tags: str = ""
    is_public: bool = True


class AlbumUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    style_tags: str | None = None
    is_public: bool | None = None
    cover_photo_id: str | None = None


class AlbumResponse(BaseModel):
    id: str
    title: str
    description: str
    cover_photo_id: str | None
    cover_url: str | None = None
    cover_access_url_endpoint: str | None = None
    style_tags: str
    is_public: bool
    photo_count: int
    owner_id: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PhotoResponse(BaseModel):
    id: str
    album_id: str
    filename: str
    mime_type: str
    size_bytes: int
    width: int
    height: int
    caption: str
    sort_order: int
    storage_backend: str = "local"
    url: str
    access_url_endpoint: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class PhotoUpdate(BaseModel):
    caption: str | None = None
    sort_order: int | None = None
