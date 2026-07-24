"""权限管理相关请求/响应 Schema。"""

from pydantic import BaseModel, Field


class PermissionDefinition(BaseModel):
    """权限定义。"""
    resource_type: str = Field(..., description="report/knowledge_base/data_dimension/system")
    resource_id: str
    access_level: str = Field(..., description="none/read/write/admin")
    department_scope: list[int] | None = None


class RoleCreateRequest(BaseModel):
    """创建角色请求。"""
    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    permissions: list[PermissionDefinition] = []


class RoleUpdateRequest(BaseModel):
    """更新角色请求。"""
    name: str | None = None
    description: str | None = None
    permissions: list[PermissionDefinition] | None = None


class RoleResponse(BaseModel):
    """角色响应。"""
    id: int
    name: str
    description: str | None
    permissions: list[PermissionDefinition] = []


class AssignRoleRequest(BaseModel):
    """分配角色请求。"""
    role_ids: list[int]


class EffectivePermissionResponse(BaseModel):
    """有效权限响应。"""
    user_id: int
    permissions: list[dict]
    roles: list[dict]
