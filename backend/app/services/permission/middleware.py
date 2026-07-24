"""权限检查中间件（FastAPI 依赖）。"""

from typing import Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.errors import PERM_001, AuthorizationException
from app.core.redis import get_redis
from app.services.auth.dependencies import get_current_user
from app.services.permission.calculator import PermissionCalculator


def check_permission(
    resource_type: str,
    resource_id: str = "*",
    required_level: str = "read",
) -> Callable:
    """
    权限检查依赖工厂。

    Usage:
        @router.get("/data", dependencies=[Depends(check_permission("report", "sales", "read"))])
        async def get_sales_data(): ...
    """

    async def _check(
        current_user: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        redis: aioredis.Redis = Depends(get_redis),
    ):
        # 无角色用户直接拒绝
        if not current_user.get("roles"):
            raise AuthorizationException(PERM_001)

        calculator = PermissionCalculator(db=db, redis=redis)
        permissions = await calculator.get_effective_permissions(current_user["user_id"])

        if not permissions:
            raise AuthorizationException(PERM_001)

        has_access = calculator.check_access(
            permissions=permissions,
            resource_type=resource_type,
            resource_id=resource_id,
            required_level=required_level,
        )

        if not has_access:
            raise AuthorizationException(PERM_001)

    return _check


async def require_admin(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """要求管理员权限的依赖。"""
    calculator = PermissionCalculator(db=db, redis=redis)
    permissions = await calculator.get_effective_permissions(current_user["user_id"])

    is_admin = any(p["access_level"] == "admin" and p["resource_type"] == "system" for p in permissions)
    if not is_admin:
        raise AuthorizationException(PERM_001)
