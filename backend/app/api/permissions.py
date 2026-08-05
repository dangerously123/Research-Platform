"""用户权限管理 API 路由：角色分配、有效权限查询。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.redis import get_redis
from app.models.user import Role, User, UserRole
from app.schemas.permission import AssignRoleRequest, EffectivePermissionResponse
from app.services.auth.dependencies import get_current_user
from app.services.permission.calculator import PermissionCalculator
from app.services.permission.middleware import require_admin

router = APIRouter()


@router.post("/{user_id}/roles", status_code=201)
async def assign_roles(
    user_id: int,
    request: AssignRoleRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    _admin=Depends(require_admin),
):
    """为用户分配角色（管理员）。"""
    for role_id in request.role_ids:
        # 检查是否已存在
        stmt = select(UserRole).where(
            UserRole.user_id == user_id, UserRole.role_id == role_id
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            continue

        user_role = UserRole(
            user_id=user_id,
            role_id=role_id,
            assigned_by=current_user["user_id"],
        )
        db.add(user_role)

    await db.flush()

    # 清除用户权限缓存，确保即时生效
    calculator = PermissionCalculator(db=db, redis=redis)
    await calculator.invalidate_cache(user_id)

    return {"message": "角色分配成功"}


@router.delete("/{user_id}/roles/{role_id}", status_code=204)
async def remove_role(
    user_id: int,
    role_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    _admin=Depends(require_admin),
):
    """移除用户角色（管理员）。"""
    stmt = delete(UserRole).where(
        UserRole.user_id == user_id, UserRole.role_id == role_id
    )
    await db.execute(stmt)

    # 清除缓存
    calculator = PermissionCalculator(db=db, redis=redis)
    await calculator.invalidate_cache(user_id)
    await redis.incr(f"rag:permission:version:{user_id}")


@router.get("/{user_id}/effective-permissions", response_model=EffectivePermissionResponse)
async def get_effective_permissions(
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """获取用户有效权限（合并多角色后）。"""
    calculator = PermissionCalculator(db=db, redis=redis)
    permissions = await calculator.get_effective_permissions(user_id)

    # 获取角色信息
    stmt = (
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    result = await db.execute(stmt)
    roles = result.scalars().all()

    return EffectivePermissionResponse(
        user_id=user_id,
        permissions=permissions,
        roles=[{"id": r.id, "name": r.name, "description": r.description} for r in roles],
    )
