from typing import Literal

from pydantic import BaseModel, Field


class InitRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    create_demo_user: bool = False


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["user"] = "user"


class UserPatchRequest(BaseModel):
    status: Literal["active", "disabled"]


class TestLLMRequest(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
