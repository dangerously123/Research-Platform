"""FastAPI 认证依赖注入。"""

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.errors import AUTH_003, AUTH_004, AuthenticationException
from app.core.redis import get_redis
from app.services.auth.session import SessionManager

# HTTP Bearer Token 提取
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> dict:
    """
    FastAPI 依赖：获取当前认证用户。
    验证 JWT Token 并检查 Redis 会话有效性。

    Returns:
        会话数据 dict，包含 user_id, username, department_id, roles 等
    """
    token = credentials.credentials
    session_manager = SessionManager(db=db, redis=redis)

    session = await session_manager.validate_session(token)
    if not session:
        raise AuthenticationException(AUTH_003)

    return session


async def get_current_user_id(
    current_user: dict = Depends(get_current_user),
) -> int:
    """FastAPI 依赖：获取当前用户 ID。"""
    return current_user["user_id"]
