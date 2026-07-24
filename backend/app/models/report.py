"""报表相关数据库模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReportConfig(Base):
    """报表配置表。"""

    __tablename__ = "report_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    report_type: Mapped[str] = mapped_column(
        Enum("table", "line_chart", "bar_chart", "pie_chart", name="report_type_enum"),
        nullable=False,
    )
    data_source: Mapped[str] = mapped_column(String(256), nullable=False)
    query_template: Mapped[str] = mapped_column(Text, nullable=False)
    access_roles: Mapped[dict | None] = mapped_column(JSON, comment="可访问该报表的角色ID列表")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ExportTask(Base):
    """报表导出任务表。"""

    __tablename__ = "export_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    report_config_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("report_configs.id"), nullable=False
    )
    format: Mapped[str] = mapped_column(
        Enum("excel", "pdf", name="export_format_enum"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "completed", "failed", name="export_status_enum"),
        default="pending",
    )
    file_path: Mapped[str | None] = mapped_column(String(512))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_user_status", "user_id", "status"),
    )
