"""Database models for Agent execution traces."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentTrace(Base):
    """One top-level Agent execution trace."""

    __tablename__ = "agent_traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="Request trace id")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger)
    query: Mapped[str] = mapped_column(Text, nullable=False, comment="Original user input")
    execution_type: Mapped[str] = mapped_column(
        Enum("react", "single_call", "pre_execute", name="agent_execution_type_enum"),
        nullable=False,
        comment="Execution type",
    )
    model_id: Mapped[str | None] = mapped_column(String(64), comment="Model id")
    exit_reason: Mapped[str | None] = mapped_column(String(32), comment="Exit reason")
    final_answer: Mapped[str | None] = mapped_column(Text, comment="Final answer")
    total_iterations: Mapped[int] = mapped_column(Integer, default=0, comment="Total reasoning iterations")
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0, comment="Total duration in milliseconds")
    quality_score: Mapped[float | None] = mapped_column(Float, comment="Quality score")
    tools_called: Mapped[dict | None] = mapped_column(JSON, comment="Called tools")
    tools_count: Mapped[int] = mapped_column(Integer, default=0, comment="Tool call count")
    tools_failed: Mapped[int] = mapped_column(Integer, default=0, comment="Failed tool call count")
    memory_used: Mapped[bool] = mapped_column(Boolean, default=False, comment="Whether memory was used")
    files_used: Mapped[dict | None] = mapped_column(JSON, comment="Related file ids")
    prompt_tokens_budget: Mapped[int | None] = mapped_column(Integer, comment="Prompt token budget")
    prompt_tokens_actual: Mapped[int | None] = mapped_column(Integer, comment="Actual prompt tokens")
    error: Mapped[str | None] = mapped_column(Text, comment="Error message")
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_trace_id", "trace_id"),
        Index("idx_user_time", "user_id", "started_at"),
        Index("idx_conversation", "conversation_id"),
        Index("idx_execution_type", "execution_type", "started_at"),
    )


class AgentTraceStep(Base):
    """One step inside an Agent execution trace."""

    __tablename__ = "agent_trace_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="Parent trace id")
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, comment="Iteration number")
    thought: Mapped[str | None] = mapped_column(Text, comment="LLM thought")
    action: Mapped[str | None] = mapped_column(String(64), comment="Tool name")
    action_input: Mapped[dict | None] = mapped_column(JSON, comment="Tool parameters")
    observation: Mapped[str | None] = mapped_column(Text, comment="Tool observation")
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, comment="Whether this is final answer step")
    duration_ms: Mapped[float] = mapped_column(Float, default=0, comment="Step duration")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_success: Mapped[bool | None] = mapped_column(Boolean, comment="Tool success")
    tool_error: Mapped[str | None] = mapped_column(String(512), comment="Tool error message")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("idx_step_trace", "trace_id", "iteration"),)
