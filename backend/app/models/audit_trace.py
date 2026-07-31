"""Agent 执行轨迹审计表 — 记录每次 Agent 调用的完整链路。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentTrace(Base):
    """
    Agent 执行轨迹表。
    每次 Agent（ReAct/单次调用）执行记录一条主轨迹。
    """

    __tablename__ = "agent_traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="请求追踪ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger)

    # 执行概况
    query: Mapped[str] = mapped_column(Text, nullable=False, comment="用户原始输入")
    execution_type: Mapped[str] = mapped_column(
        Enum("react", "single_call", "pre_execute", name="agent_execution_type_enum"),
        nullable=False,
        comment="执行类型",
    )
    model_id: Mapped[str | None] = mapped_column(String(64), comment="使用的模型")
    exit_reason: Mapped[str | None] = mapped_column(String(32), comment="退出原因")
    final_answer: Mapped[str | None] = mapped_column(Text, comment="最终回答")

    # 性能指标
    total_iterations: Mapped[int] = mapped_column(Integer, default=0, comment="总推理轮数")
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0, comment="总耗时(毫秒)")
    quality_score: Mapped[float | None] = mapped_column(Float, comment="质量评分")

    # 工具调用统计
    tools_called: Mapped[dict | None] = mapped_column(
        JSON, comment="调用的工具列表 [{name, params, success, duration_ms}]"
    )
    tools_count: Mapped[int] = mapped_column(Integer, default=0, comment="工具调用总次数")
    tools_failed: Mapped[int] = mapped_column(Integer, default=0, comment="工具失败次数")

    # 上下文信息
    memory_used: Mapped[bool] = mapped_column(default=False, comment="是否使用了长期记忆")
    files_used: Mapped[dict | None] = mapped_column(JSON, comment="关联的文件ID列表")
    prompt_tokens_budget: Mapped[int | None] = mapped_column(Integer, comment="Prompt预算(tokens)")
    prompt_tokens_actual: Mapped[int | None] = mapped_column(Integer, comment="实际Prompt消耗(tokens)")

    # 错误信息
    error: Mapped[str | None] = mapped_column(Text, comment="如果失败，错误信息")

    # 时间
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_trace_id", "trace_id"),
        Index("idx_user_time", "user_id", "started_at"),
        Index("idx_conversation", "conversation_id"),
        Index("idx_execution_type", "execution_type", "started_at"),
    )


class AgentTraceStep(Base):
    """
    Agent 执行步骤明细表。
    每个 ReAct 循环的每一步记录一条。
    """

    __tablename__ = "agent_trace_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="关联的追踪ID")
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, comment="第N轮")

    # 推理内容
    thought: Mapped[str | None] = mapped_column(Text, comment="LLM 思考过程")
    action: Mapped[str | None] = mapped_column(String(64), comment="工具名称")
    action_input: Mapped[dict | None] = mapped_column(JSON, comment="工具参数")
    observation: Mapped[str | None] = mapped_column(Text, comment="工具执行结果")
    is_final: Mapped[bool] = mapped_column(default=False, comment="是否为最终回答步骤")

    # 性能
    duration_ms: Mapped[float] = mapped_column(Float, default=0, comment="本步耗时")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # 工具结果
    tool_success: Mapped[bool | None] = mapped_column(comment="工具是否成功")
    tool_error: Mapped[str | None] = mapped_column(String(512), comment="工具错误信息")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_step_trace", "trace_id", "iteration"),
    )
