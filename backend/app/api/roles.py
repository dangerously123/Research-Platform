"""角色管理 API 路由。"""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.errors import PERM_002, PERM_003, NotFoundException, AppException
from app.core.redis import get_redis
from app.models.user import Permission, Role, UserRole
from app.schemas.permission import (
    PermissionDefinition,
    RoleCreateRequest,
    RoleResponse,
    RoleUpdateRequest,
)
from app.services.auth.dependencies import get_current_user
from app.services.permission.middleware import require_admin

router = APIRouter()


@router.get("", response_model=list[RoleResponse])
async def list_roles(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取角色列表。"""
    stmt = select(Role).options(selectinload(Role.permissions))
    result = await db.execute(stmt)
    roles = result.scalars().all()

    return [
        RoleResponse(
            id=role.id,
            name=role.name,
            description=role.description,
            permissions=[
                PermissionDefinition(
                    resource_type=p.resource_type,
                    resource_id=p.resource_id,
                    access_level=p.access_level,
                    department_scope=json.loads(p.department_scope) if p.department_scope else None,
                )
                for p in role.permissions
            ],
        )
        for role in roles
    ]


@router.post("", response_model=RoleResponse, status_code=201)
async def create_role(
    request: RoleCreateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """创建角色（管理员）。"""
    role = Role(name=request.name, description=request.description)
    db.add(role)
    await db.flush()

    # 添加权限定义
    for perm_def in request.permissions:
        perm = Permission(
            role_id=role.id,
            resource_type=perm_def.resource_type,
            resource_id=perm_def.resource_id,
            access_level=perm_def.access_level,
            department_scope=json.dumps(perm_def.department_scope) if perm_def.department_scope else None,
        )
        db.add(perm)

    await db.flush()

    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=request.permissions,
    )


@router.put("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int,
    request: RoleUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    _admin=Depends(require_admin),
):
    """更新角色（管理员）。"""
    stmt = select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()

    if not role:
        raise NotFoundException(PERM_002)

    if request.name is not None:
        role.name = request.name
    if request.description is not None:
        role.description = request.description

    if request.permissions is not None:
        # 删除旧权限，添加新权限
        for old_perm in role.permissions:
            await db.delete(old_perm)

        for perm_def in request.permissions:
            perm = Permission(
                role_id=role.id,
                resource_type=perm_def.resource_type,
                resource_id=perm_def.resource_id,
                access_level=perm_def.access_level,
                department_scope=json.dumps(perm_def.department_scope) if perm_def.department_scope else None,
            )
            db.add(perm)

    await db.flush()

    # 清除所有关联用户的权限缓存
    user_role_stmt = select(UserRole.user_id).where(UserRole.role_id == role_id)
    user_ids_result = await db.execute(user_role_stmt)
    for (uid,) in user_ids_result:
        await redis.delete(f"perm:user:{uid}")

    final_permissions = request.permissions if request.permissions is not None else [
        PermissionDefinition(
            resource_type=p.resource_type,
            resource_id=p.resource_id,
            access_level=p.access_level,
            department_scope=json.loads(p.department_scope) if p.department_scope else None,
        )
        for p in role.permissions
    ]

    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=final_permissions,
    )


@router.delete("/{role_id}", status_code=204)
async def delete_role(
    role_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """删除角色（管理员）。检查是否有用户关联。"""
    # 检查角色是否存在
    stmt = select(Role).where(Role.id == role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()
    if not role:
        raise NotFoundException(PERM_002)

    # 检查是否有用户关联
    user_role_stmt = select(UserRole).where(UserRole.role_id == role_id).limit(1)
    ur_result = await db.execute(user_role_stmt)
    if ur_result.scalar_one_or_none():
        raise AppException(PERM_003, status_code=409)

    await db.delete(role)
