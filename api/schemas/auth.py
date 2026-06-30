from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=128)


class UserProfile(BaseModel):
    id: int
    username: str
    email: str
    avatar_sha256: str
    display_name: str
    user_type: str
    preferred_language: Literal["en", "zh"]
    light_background: str
    dark_background: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


class UserPreferencesUpdateRequest(BaseModel):
    preferred_language: Literal["en", "zh"]
    light_background: str = Field(..., min_length=1, max_length=255)
    dark_background: str = Field(..., min_length=1, max_length=255)
