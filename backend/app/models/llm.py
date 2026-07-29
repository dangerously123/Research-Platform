"""LLM 相关数据库模型：对话、消息、Prompt模板、Token用量、模型配置、安全事件。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class LLMConversation(Base):
    """LLM 对话会话表。"""

    __tablename__ = "llm_conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(256), comment="会话标题")
    status: Mapped[str] = mapped_column(
        Enum("active", "archived", "deleted", name="conversation_status_enum"),
        default="active",
    )
    model_id: Mapped[str | None] = mapped_column(String(64), comment="当前会话使用的模型标识")
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # 关联
    messages: Mapped[list["LLMMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_user_status", "user_id", "status"),
        Index("idx_last_active", "last_active_at"),
    )


class LLMMessage(Base):
    """对话消息表。"""

    __tablename__ = "llm_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("llm_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        Enum("user", "assistant", "system", name="message_role_enum"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model_id: Mapped[str | None] = mapped_column(String(64))
    sources: Mapped[dict | None] = mapped_column(JSON, comment="引用的文档来源列表")
    relevance_score: Mapped[float | None] = mapped_column(Float, comment="回答与检索文档的相关度评分")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 关联
    conversation: Mapped["LLMConversation"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("idx_conversation_time", "conversation_id", "created_at"),
    )


class PromptTemplate(Base):
    """Prompt 模板表。"""

    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(
        Enum("tech_doc", "data_analysis", "process_guide", "general", name="prompt_category_enum"),
        nullable=False,
        default="general",
    )
    template_content: Mapped[str] = mapped_column(Text, nullable=False, comment="模板内容，含变量占位符")
    variables: Mapped[dict | None] = mapped_column(JSON, comment="支持的变量列表及描述")
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # 关联
    versions: Mapped[list["PromptTemplateVersion"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_category_active", "category", "is_active"),
    )


class PromptTemplateVersion(Base):
    """Prompt 模板版本历史表。"""

    __tablename__ = "prompt_template_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    template_content: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[dict | None] = mapped_column(JSON)
    changed_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    change_description: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 关联
    template: Mapped["PromptTemplate"] = relationship(back_populates="versions")

    __table_args__ = (
        Index("idx_template_version", "template_id", "version"),
    )


class TokenUsageRecord(Base):
    """Token 用量记录表。"""

    __tablename__ = "token_usage_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    department_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), comment="估算费用（元）")
    request_type: Mapped[str] = mapped_column(
        Enum("chat", "regenerate", "summary", name="request_type_enum"),
        nullable=False,
        default="chat",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_user_time", "user_id", "created_at"),
        Index("idx_department_time", "department_id", "created_at"),
        Index("idx_model_time", "model_id", "created_at"),
    )


class TokenQuota(Base):
    """Token 配额表。"""

    __tablename__ = "token_quotas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(
        Enum("user", "department", name="quota_target_type_enum"),
        nullable=False,
    )
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    monthly_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="月度 Token 配额")
    monthly_cost_limit: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), comment="月度费用上限（元）")
    current_month_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    current_month_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    alert_threshold: Mapped[float] = mapped_column(Float, default=0.8, comment="预警阈值百分比")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_target", "target_type", "target_id", unique=True),
    )


class LLMModelConfig(Base):
    """LLM 模型配置表。"""

    __tablename__ = "llm_model_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="模型标识符")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="显示名称")
    provider: Mapped[str] = mapped_column(
        Enum("ollama", "vllm", "openai", "qwen", "wenxin", name="llm_provider_enum"),
        nullable=False,
    )
    endpoint_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_ref: Mapped[str | None] = mapped_column(String(256), comment="KMS 中的密钥引用")
    priority: Mapped[int] = mapped_column(Integer, default=0, comment="优先级，数值越小优先级越高")
    context_window: Mapped[int] = mapped_column(
        Integer, default=8192, comment="模型上下文窗口大小（总 Token 数）"
    )
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    task_types: Mapped[dict | None] = mapped_column(JSON, comment="适用的任务类型列表")
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "error", name="model_status_enum"),
        default="active",
    )
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime)
    avg_latency_ms: Mapped[int | None] = mapped_column(Integer, comment="平均响应延迟（毫秒）")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_provider_status", "provider", "status"),
        Index("idx_priority", "priority"),
    )


class LLMSecurityEvent(Base):
    """LLM 安全事件日志表。"""

    __tablename__ = "llm_security_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(
        Enum(
            "prompt_injection", "pii_detected", "classification_blocked",
            "rate_limited", "key_anomaly",
            name="llm_security_event_type_enum",
        ),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", "critical", name="llm_event_severity_enum"),
        nullable=False,
    )
    input_content: Mapped[str | None] = mapped_column(Text, comment="触发事件的输入内容（脱敏后）")
    detection_details: Mapped[dict | None] = mapped_column(JSON, comment="检测详情")
    action_taken: Mapped[str | None] = mapped_column(String(64), comment="采取的动作")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_user_type", "user_id", "event_type"),
        Index("idx_severity_time", "severity", "created_at"),
    )
