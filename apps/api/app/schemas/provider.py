from datetime import datetime

from pydantic import BaseModel, Field


class ProviderConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider_type: str = Field(default="text", max_length=32)
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    is_enabled: bool = True
    priority: int = 1
    timeout_seconds: int = Field(default=60, ge=5, le=600)


class ProviderConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider_type: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # 空或不传 = 不改密钥
    default_model: str | None = None
    is_enabled: bool | None = None
    priority: int | None = None
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)


class ProviderConfigResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    base_url: str
    default_model: str
    is_enabled: bool
    priority: int
    timeout_seconds: int = 60
    created_at: datetime
    has_api_key: bool = False
    api_key_fingerprint: str = ""
    model_config = {"from_attributes": True}


class ProviderPublicItem(BaseModel):
    """登录用户可见的脱敏目录。"""

    id: str
    name: str
    provider_type: str
    default_model: str
    is_enabled: bool = True
    source: str = "db"
    # 健康探测结果（mock 恒 true；openai_compatible 探测 base_url 可达性）
    healthy: bool = True
