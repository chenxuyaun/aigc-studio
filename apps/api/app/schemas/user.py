from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    password: str | None = None
    is_active: bool | None = None
