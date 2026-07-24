"""用户记忆相关数据库模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
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


class MemoryRecord(Base):
    """
    用户记忆元数据表。
    向量数据存储在 ChromaDB/Milvus 中，此表存储结构化元数据供管理和展示。
    """

    __tablename__ = "memory_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 记忆内容
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="用户原始问题")
    answer_summary: Mapped[str] = mapped_column(
        Text, nullable=False, comment="回答摘要（200字以内）"
    )
    key_facts: Mapped[dict | None] = mapped_column(
        JSON, comment="从回答中提取的关键事实列表"
    )
    topic_tags: Mapped[str | None] = mapped_column(
        String(256), comment="主题标签，逗号分隔"
    )

    # 记忆管理
    importance: Mapped[float] = mapped_column(
        Float, default=0.5, comment="重要性评分 0-1"
    )
    access_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="被回忆引用次数"
    )
    vector_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="向量库中的记录ID"
    )

    # 来源追踪
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="来源会话ID"
    )
    source_message_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="来源消息ID"
    )

    # 时间管理
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="最后被引用时间"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, comment="过期时间（可选，实现记忆衰减）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_user_active", "user_id", "is_active"),
        Index("idx_user_importance", "user_id", "importance"),
        Index("idx_user_topic", "user_id", "topic_tags"),
        Index("idx_last_accessed", "last_accessed_at"),
    )
