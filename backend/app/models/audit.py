"""审计日志与安全相关数据库模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """审计日志表。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operation_type: Mapped[str] = mapped_column(
        Enum(
            "login", "logout", "query", "export",
            "permission_change", "role_change", "config_change",
            name="operation_type_enum",
        ),
        nullable=False,
    )
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    data_scope: Mapped[str | None] = mapped_column(Text, comment="涉及数据范围描述")
    details: Mapped[dict | None] = mapped_column(JSON, comment="操作详情")
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_user_time", "user_id", "created_at"),
        Index("idx_operation", "operation_type", "created_at"),
    )


class PermissionChangeLog(Base):
    """权限变更日志表。"""

    __tablename__ = "permission_change_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_type: Mapped[str] = mapped_column(
        Enum("role", "user_role", "permission", name="perm_change_target_enum"),
        nullable=False,
    )
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(
        Enum("create", "update", "delete", name="perm_change_action_enum"),
        nullable=False,
    )
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_operator_time", "operator_id", "created_at"),
    )


class SecurityAlert(Base):
    """安全告警表。"""

    __tablename__ = "security_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_type: Mapped[str] = mapped_column(
        Enum(
            "abnormal_access", "brute_force", "data_leak_attempt", "unauthorized_access",
            name="alert_type_enum",
        ),
        nullable=False,
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", "critical", name="severity_enum"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum("open", "acknowledged", "resolved", name="alert_status_enum"),
        default="open",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_status_severity", "status", "severity"),
    )
