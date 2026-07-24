"""审计日志模块：统一记录所有数据操作和权限变更。"""

import json
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog, PermissionChangeLog


class AuditLogger:
    """
    统一审计日志记录器。
    覆盖所有数据查询、导出操作和权限变更。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_operation(
        self,
        user_id: int,
        operation_type: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        data_scope: str | None = None,
        details: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """
        记录操作审计日志。

        Args:
            user_id: 操作用户 ID
            operation_type: 操作类型 (login/logout/query/export/permission_change/role_change/config_change)
            resource_type: 资源类型
            resource_id: 资源 ID
            data_scope: 涉及数据范围描述
            details: 操作详情
            ip_address: 客户端 IP
            user_agent: 客户端 UA
        """
        log_entry = AuditLog(
            user_id=user_id,
            operation_type=operation_type,
            resource_type=resource_type,
            resource_id=resource_id,
            data_scope=data_scope,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.add(log_entry)
        await self.db.flush()

    async def log_permission_change(
        self,
        operator_id: int,
        target_type: str,
        target_id: int,
        action: str,
        old_value: dict | None = None,
        new_value: dict | None = None,
    ) -> None:
        """
        记录权限变更审计日志。

        Args:
            operator_id: 操作人 ID
            target_type: 变更目标类型 (role/user_role/permission)
            target_id: 变更目标 ID
            action: 操作类型 (create/update/delete)
            old_value: 变更前的值
            new_value: 变更后的值
        """
        log_entry = PermissionChangeLog(
            operator_id=operator_id,
            target_type=target_type,
            target_id=target_id,
            action=action,
            old_value=old_value,
            new_value=new_value,
        )
        self.db.add(log_entry)
        await self.db.flush()

    async def log_llm_call(
        self,
        user_id: int,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        status: str,
        ip_address: str | None = None,
    ) -> None:
        """记录 LLM 调用审计日志。"""
        await self.log_operation(
            user_id=user_id,
            operation_type="query",
            resource_type="llm_model",
            resource_id=model_id,
            details={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "status": status,
            },
            ip_address=ip_address,
        )
