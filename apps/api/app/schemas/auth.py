from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
