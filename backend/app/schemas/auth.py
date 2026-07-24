"""认证相关请求/响应 Schema。"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求。"""
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class UserInfo(BaseModel):
    """用户基本信息。"""
    id: int
    username: str
    email: str | None = None
    department_id: int
    position: str | None = None
    roles: list[int] = []


class LoginResponse(BaseModel):
    """登录响应。"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


class CurrentUserResponse(BaseModel):
    """当前用户信息响应。"""
    user: UserInfo
    roles: list[dict] = []
    permissions: list[dict] = []
