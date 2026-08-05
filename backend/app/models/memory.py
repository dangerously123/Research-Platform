"""Database model for user memories."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MemoryRecord(Base):
    """Structured metadata for user memories stored in the vector database."""

    __tablename__ = "memory_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="Original user question")
    answer_summary: Mapped[str] = mapped_column(Text, nullable=False, comment="Short answer summary")
    key_facts: Mapped[list | None] = mapped_column(JSON, comment="Extracted key facts")
    topic_tags: Mapped[str | None] = mapped_column(String(256), comment="Comma-separated topic tags")
    importance: Mapped[float] = mapped_column(Float, default=0.5, comment="Importance score from 0 to 1")
    access_count: Mapped[int] = mapped_column(Integer, default=0, comment="Recall count")
    vector_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="Vector-store record id")
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, comment="Source conversation id")
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, comment="Source message id")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="Last recall time")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, comment="Optional expiry time")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_user_active", "user_id", "is_active"),
        Index("idx_user_importance", "user_id", "importance"),
        Index("idx_user_topic", "user_id", "topic_tags"),
        Index("idx_last_accessed", "last_accessed_at"),
    )
