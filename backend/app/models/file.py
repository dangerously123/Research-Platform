"""Uploaded file metadata models."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UploadedFile(Base):
    """Metadata for a user-uploaded file."""

    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="Related conversation ID")
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="Related message ID")

    original_name: Mapped[str] = mapped_column(String(256), nullable=False, comment="Original filename")
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False, comment="Relative storage path")
    file_type: Mapped[str] = mapped_column(
        Enum("image", "pdf", "excel", "csv", "word", "text", "other", name="file_type_enum"),
        nullable=False,
        comment="File type category",
    )
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, comment="MIME type")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="File size in bytes")

    process_status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "completed", "failed", name="file_process_status_enum"),
        default="pending",
        nullable=False,
        comment="Processing status",
    )
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="Processing error")

    extracted_content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Extracted text content")
    extracted_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="Structured metadata")
    image_description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Image description")
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="OCR text")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="Processed at")

    __table_args__ = (
        Index("idx_user_files", "user_id", "created_at"),
        Index("idx_conversation_files", "conversation_id"),
        Index("idx_process_status", "process_status"),
    )
