"""用户、角色、权限、部门相关数据库模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    """用户表。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    department_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("departments.id"), nullable=False)
    position: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        Enum("active", "locked", "disabled", name="user_status"),
        default="active",
    )
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # 关联
    department: Mapped["Department"] = relationship(back_populates="users")
    user_roles: Mapped[list["UserRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_department", "department_id"),
        Index("idx_status", "status"),
    )


class Role(Base):
    """角色表。"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # 关联
    permissions: Mapped[list["Permission"]] = relationship(back_populates="role", cascade="all, delete-orphan")
    user_roles: Mapped[list["UserRole"]] = relationship(back_populates="role", cascade="all, delete-orphan")


class Permission(Base):
    """权限定义表。"""

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    resource_type: Mapped[str] = mapped_column(
        Enum("report", "knowledge_base", "data_dimension", "system", name="resource_type_enum"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    access_level: Mapped[str] = mapped_column(
        Enum("none", "read", "write", "admin", name="access_level_enum"),
        nullable=False,
        default="read",
    )
    department_scope: Mapped[str | None] = mapped_column(String(256), comment="部门范围限制，JSON数组")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 关联
    role: Mapped["Role"] = relationship(back_populates="permissions")

    __table_args__ = (
        Index("idx_role_resource", "role_id", "resource_type", "resource_id"),
    )


class UserRole(Base):
    """用户角色关联表。"""

    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    assigned_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 关联
    user: Mapped["User"] = relationship(back_populates="user_roles")
    role: Mapped["Role"] = relationship(back_populates="user_roles")


class Department(Base):
    """部门表。"""

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("departments.id"))
    path: Mapped[str | None] = mapped_column(String(512), comment="部门层级路径")

    # 关联
    users: Mapped[list["User"]] = relationship(back_populates="department")
    children: Mapped[list["Department"]] = relationship(back_populates="parent")
    parent: Mapped["Department | None"] = relationship(
        back_populates="children", remote_side=[id]
    )
