"""权限计算器：多角色权限合并，最高权限优先原则。"""

import json

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.user import Permission, Role, User, UserRole


# 权限级别优先级映射
ACCESS_LEVEL_PRIORITY = {"none": 0, "read": 1, "write": 2, "admin": 3}


class PermissionCalculator:
    """
    权限计算器。
    - 合并用户所有角色的权限定义
    - 对同一资源的不同权限级别，取最高级别（最高权限优先原则）
    - 使用 Redis 缓存有效权限（TTL=5min）
    """

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def get_effective_permissions(self, user_id: int) -> list[dict]:
        """
        获取用户的有效权限列表（合并多角色后）。
        优先从 Redis 缓存读取。
        """
        cache_key = f"perm:user:{user_id}"

        # 尝试从缓存读取
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)

        # 从数据库计算
        permissions = await self._calculate_from_db(user_id)

        # 写入缓存
        await self.redis.setex(cache_key, 300, json.dumps(permissions))  # TTL=5min

        return permissions

    async def invalidate_cache(self, user_id: int) -> None:
        """清除用户权限缓存。"""
        await self.redis.delete(f"perm:user:{user_id}")

    async def _calculate_from_db(self, user_id: int) -> list[dict]:
        """从数据库计算用户有效权限。"""
        # 查询用户的所有角色及其权限
        stmt = (
            select(Permission)
            .join(Role, Permission.role_id == Role.id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        all_permissions = result.scalars().all()

        # 合并权限：同一资源取最高级别
        permission_map: dict[str, dict] = {}

        for perm in all_permissions:
            key = f"{perm.resource_type}:{perm.resource_id}"
            if key not in permission_map:
                permission_map[key] = {
                    "resource_type": perm.resource_type,
                    "resource_id": perm.resource_id,
                    "access_level": perm.access_level,
                    "department_scope": perm.department_scope,
                }
            else:
                existing = permission_map[key]
                if ACCESS_LEVEL_PRIORITY.get(perm.access_level, 0) > ACCESS_LEVEL_PRIORITY.get(
                    existing["access_level"], 0
                ):
                    permission_map[key] = {
                        "resource_type": perm.resource_type,
                        "resource_id": perm.resource_id,
                        "access_level": perm.access_level,
                        "department_scope": perm.department_scope,
                    }

        return list(permission_map.values())

    def check_access(
        self,
        permissions: list[dict],
        resource_type: str,
        resource_id: str,
        required_level: str,
    ) -> bool:
        """
        检查用户是否有权访问指定资源。

        Args:
            permissions: 用户有效权限列表
            resource_type: 资源类型
            resource_id: 资源 ID
            required_level: 需要的最低权限级别
        """
        required_priority = ACCESS_LEVEL_PRIORITY.get(required_level, 0)

        for perm in permissions:
            if perm["resource_type"] == resource_type and perm["resource_id"] == resource_id:
                user_priority = ACCESS_LEVEL_PRIORITY.get(perm["access_level"], 0)
                return user_priority >= required_priority

            # admin 资源类型有全局访问权
            if perm["resource_type"] == resource_type and perm["access_level"] == "admin":
                return True

        return False
