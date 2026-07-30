"""上传文件元数据数据库模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UploadedFile(Base):
    """上传文件元数据表。"""

    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="关联的会话ID"
    )
    message_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="关联的消息ID"
    )

    # 文件基本信息
    original_name: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="原始文件名"
    )
    storage_path: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="存储路径"
    )
    file_type: Mapped[str] = mapped_column(
        Enum("image", "pdf", "excel", "csv", "word", "text", "other", name="file_type_enum"),
        nullable=False,
        comment="文件类型分类",
    )
    mime_type: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="MIME 类型"
    )
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="文件大小(bytes)"
    )

    # 处理状态
    process_status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "completed", "failed", name="file_process_status_enum"),
        default="pending",
        comment="处理状态",
    )
    error_message: Mapped[str | None] = mapped_column(
        String(512), comment="处理失败时的错误信息"
    )

    # 提取的内容
    extracted_content: Mapped[str | None] = mapped_column(
        Text, comment="提取的文本内容（摘要或全文）"
    )
    extracted_metadata: Mapped[dict | None] = mapped_column(
        JSON, comment="结构化元数据（列名、行数、统计信息等）"
    )

    # 图片特有字段
    image_description: Mapped[str | None] = mapped_column(
        Text, comment="VLM 生成的图片描述"
    )
    ocr_text: Mapped[str | None] = mapped_column(
        Text, comment="OCR 识别的文本"
    )

    # 时间
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="处理完成时间"
    )

    __table_args__ = (
        Index("idx_user_files", "user_id", "created_at"),
        Index("idx_conversation_files", "conversation_id"),
        Index("idx_process_status", "process_status"),
    )
