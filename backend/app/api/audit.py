"""Audit log API routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.audit import AuditLog
from app.services.auth.dependencies import get_current_user
from app.services.permission.middleware import require_admin

router = APIRouter()


def _serialize_log(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "user_id": log.user_id,
        "operation_type": log.operation_type,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "data_scope": log.data_scope,
        "details": log.details,
        "ip_address": log.ip_address,
        "user_agent": log.user_agent,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


@router.get("/logs")
async def list_audit_logs(
    operation_type: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """List audit logs for administrators."""
    conditions = []
    if operation_type:
        conditions.append(AuditLog.operation_type == operation_type)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)

    total = (await db.execute(select(func.count(AuditLog.id)).where(*conditions))).scalar() or 0
    result = await db.execute(
        select(AuditLog)
        .where(*conditions)
        .order_by(desc(AuditLog.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = [_serialize_log(log) for log in result.scalars().all()]
    return {"logs": logs, "total": total, "page": page, "page_size": page_size}


@router.get("/stats")
async def get_audit_stats(
    days: int = Query(default=7, ge=1, le=90),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Return lightweight audit-log counts grouped by operation type."""
    from datetime import timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(AuditLog.operation_type, func.count(AuditLog.id)).where(AuditLog.created_at >= since).group_by(AuditLog.operation_type)
    )
    by_operation = {operation_type: count for operation_type, count in result.all()}
    return {"period_days": days, "by_operation": by_operation, "total": sum(by_operation.values())}
