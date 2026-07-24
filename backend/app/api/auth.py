"""认证相关 API 路由。"""

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.redis import get_redis
from app.schemas.auth import CurrentUserResponse, LoginRequest, LoginResponse, UserInfo
from app.services.auth.dependencies import get_current_user
from app.services.auth.session import SessionManager

router = APIRouter()
security = HTTPBearer()


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """用户登录，返回 JWT Token。"""
    session_manager = SessionManager(db=db, redis=redis)
    result = await session_manager.authenticate(
        username=request.username,
        password=request.password,
    )
    return result


@router.post("/logout", status_code=204)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """用户登出，删除会话。"""
    session_manager = SessionManager(db=db, redis=redis)
    await session_manager.logout(credentials.credentials)


@router.get("/me", response_model=CurrentUserResponse)
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户信息和权限。"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.user import User, UserRole, Role, Permission

    # 查询完整用户信息（含角色和权限）
    stmt = (
        select(User)
        .options(
            selectinload(User.user_roles)
            .selectinload(UserRole.role)
            .selectinload(Role.permissions)
        )
        .where(User.id == current_user["user_id"])
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        from app.core.errors import AUTH_004, AuthenticationException
        raise AuthenticationException(AUTH_004)

    # 构建角色列表
    roles = []
    permissions = []
    for ur in user.user_roles:
        role = ur.role
        roles.append({"id": role.id, "name": role.name, "description": role.description})
        for perm in role.permissions:
            permissions.append({
                "id": perm.id,
                "resource_type": perm.resource_type,
                "resource_id": perm.resource_id,
                "access_level": perm.access_level,
                "department_scope": perm.department_scope,
            })

    return CurrentUserResponse(
        user=UserInfo(
            id=user.id,
            username=user.username,
            email=user.email,
            department_id=user.department_id,
            position=user.position,
            roles=[ur.role_id for ur in user.user_roles],
        ),
        roles=roles,
        permissions=permissions,
    )
