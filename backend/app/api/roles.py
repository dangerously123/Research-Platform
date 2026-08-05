"""Role management API routes."""

import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.errors import PERM_002, PERM_003, AppException, NotFoundException
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


def _serialize_permissions(permissions: list[Permission]) -> list[PermissionDefinition]:
    return [
        PermissionDefinition(
            resource_type=permission.resource_type,
            resource_id=permission.resource_id,
            access_level=permission.access_level,
            department_scope=json.loads(permission.department_scope) if permission.department_scope else None,
        )
        for permission in permissions
    ]


def _build_permission(role_id: int, permission: PermissionDefinition) -> Permission:
    return Permission(
        role_id=role_id,
        resource_type=permission.resource_type,
        resource_id=permission.resource_id,
        access_level=permission.access_level,
        department_scope=json.dumps(permission.department_scope) if permission.department_scope else None,
    )


async def _get_role_or_404(db: AsyncSession, role_id: int) -> Role:
    stmt = select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
    result = await db.execute(stmt)
    role = result.scalar_one_or_none()
    if not role:
        raise NotFoundException(PERM_002)
    return role


async def _get_role_user_ids(db: AsyncSession, role_id: int) -> list[int]:
    result = await db.execute(select(UserRole.user_id).where(UserRole.role_id == role_id))
    return [user_id for (user_id,) in result.all()]


async def _invalidate_permission_cache(redis: aioredis.Redis, user_ids: list[int]) -> None:
    for user_id in set(user_ids):
        await redis.delete(f"perm:user:{user_id}")
        await redis.incr(f"rag:permission:version:{user_id}")


@router.get("", response_model=list[RoleResponse])
async def list_roles(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List roles."""
    stmt = select(Role).options(selectinload(Role.permissions))
    result = await db.execute(stmt)
    roles = result.scalars().all()

    return [
        RoleResponse(
            id=role.id,
            name=role.name,
            description=role.description,
            permissions=_serialize_permissions(role.permissions),
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
    """Create a role."""
    role = Role(name=request.name, description=request.description)
    db.add(role)
    await db.flush()

    for permission in request.permissions:
        db.add(_build_permission(role.id, permission))

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
    """Update a role and invalidate affected user permission caches."""
    role = await _get_role_or_404(db, role_id)
    affected_user_ids = await _get_role_user_ids(db, role_id)

    if request.name is not None:
        role.name = request.name
    if request.description is not None:
        role.description = request.description

    if request.permissions is not None:
        for old_permission in list(role.permissions):
            await db.delete(old_permission)
        await db.flush()

        for permission in request.permissions:
            db.add(_build_permission(role.id, permission))

    await db.flush()
    await _invalidate_permission_cache(redis, affected_user_ids)

    final_permissions = request.permissions if request.permissions is not None else _serialize_permissions(role.permissions)
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
    """Delete an unused role."""
    role = await _get_role_or_404(db, role_id)

    user_role_stmt = select(UserRole).where(UserRole.role_id == role_id).limit(1)
    user_role_result = await db.execute(user_role_stmt)
    if user_role_result.scalar_one_or_none():
        raise AppException(PERM_003, status_code=409)

    await db.delete(role)
