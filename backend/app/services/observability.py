"""
可观测性服务：Agent 执行轨迹记录。

职责：
- 在 Agent 执行前创建 trace 记录
- 每步推理后写入 step 明细
- 执行结束后更新 trace 汇总信息
- 提供查询接口供 API 层调用
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, get_trace_id
from app.models.audit_trace import AgentTrace, AgentTraceStep

logger = get_logger(__name__)


class TraceRecorder:
    """
    Agent 轨迹记录器。

    使用方式：
        recorder = TraceRecorder(db)
        await recorder.start_trace(user_id=1, query="...", execution_type="react")
        await recorder.record_step(iteration=1, thought="...", action="calc", ...)
        await recorder.complete_trace(final_answer="...", exit_reason="final_answer")
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._trace: AgentTrace | None = None
        self._start_time: float = 0
        self._tools_called: list[dict] = []

    @property
    def trace_id(self) -> str:
        """当前 trace_id。"""
        return get_trace_id() or ""

    async def start_trace(
        self,
        user_id: int,
        query: str,
        execution_type: str = "react",
        conversation_id: int | None = None,
        model_id: str | None = None,
        files_used: list[int] | None = None,
        prompt_tokens_budget: int | None = None,
    ) -> AgentTrace:
        """开始记录一次 Agent 执行。"""
        self._start_time = time.perf_counter()

        self._trace = AgentTrace(
            trace_id=self.trace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            query=query,
            execution_type=execution_type,
            model_id=model_id,
            files_used=files_used,
            prompt_tokens_budget=prompt_tokens_budget,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(self._trace)
        await self.db.flush()

        logger.info(
            f"[Trace] Started: type={execution_type} user={user_id} query={query[:50]}...",
            extra={"trace_id": self.trace_id},
        )
        return self._trace

    async def record_step(
        self,
        iteration: int,
        thought: str = "",
        action: str | None = None,
        action_input: dict | None = None,
        observation: str = "",
        is_final: bool = False,
        duration_ms: float = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_success: bool | None = None,
        tool_error: str | None = None,
    ) -> AgentTraceStep:
        """记录一步推理/工具调用。"""
        step = AgentTraceStep(
            trace_id=self.trace_id,
            iteration=iteration,
            thought=thought[:2000] if thought else None,  # 截断过长内容
            action=action,
            action_input=action_input,
            observation=observation[:2000] if observation else None,
            is_final=is_final,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_success=tool_success,
            tool_error=tool_error,
        )
        self.db.add(step)
        await self.db.flush()

        # 记录工具调用
        if action:
            self._tools_called.append({
                "name": action,
                "params": action_input,
                "success": tool_success,
                "duration_ms": duration_ms,
                "iteration": iteration,
            })

        logger.info(
            f"[Trace] Step {iteration}: "
            + (f"action={action}" if action else "thought_only")
            + (f" success={tool_success}" if tool_success is not None else ""),
            extra={
                "iteration": iteration,
                "tool_name": action,
                "duration_ms": duration_ms,
            },
        )

        return step

    async def complete_trace(
        self,
        final_answer: str = "",
        exit_reason: str = "",
        model_id: str | None = None,
        total_iterations: int = 0,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        quality_score: float | None = None,
        memory_used: bool = False,
        prompt_tokens_actual: int | None = None,
        error: str | None = None,
    ) -> None:
        """完成轨迹记录（成功或失败）。"""
        if not self._trace:
            return

        duration_ms = (time.perf_counter() - self._start_time) * 1000

        self._trace.final_answer = final_answer[:5000] if final_answer else None
        self._trace.exit_reason = exit_reason
        self._trace.model_id = model_id or self._trace.model_id
        self._trace.total_iterations = total_iterations
        self._trace.total_input_tokens = total_input_tokens
        self._trace.total_output_tokens = total_output_tokens
        self._trace.duration_ms = duration_ms
        self._trace.quality_score = quality_score
        self._trace.memory_used = memory_used
        self._trace.prompt_tokens_actual = prompt_tokens_actual
        self._trace.error = error
        self._trace.completed_at = datetime.now(timezone.utc)

        # 工具统计
        self._trace.tools_called = self._tools_called
        self._trace.tools_count = len(self._tools_called)
        self._trace.tools_failed = sum(1 for t in self._tools_called if t.get("success") is False)

        await self.db.flush()

        level = "error" if error else "info"
        getattr(logger, level)(
            f"[Trace] Completed: exit={exit_reason} "
            f"iterations={total_iterations} tokens={total_input_tokens}+{total_output_tokens} "
            f"duration={duration_ms:.0f}ms tools={self._trace.tools_count}",
            extra={
                "duration_ms": duration_ms,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "model_id": model_id,
            },
        )


# ============================================================
# 查询服务
# ============================================================

class TraceQueryService:
    """轨迹查询服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """获取单条轨迹详情（含所有步骤）。"""
        # 查主轨迹
        stmt = select(AgentTrace).where(AgentTrace.trace_id == trace_id)
        result = await self.db.execute(stmt)
        trace = result.scalar_one_or_none()
        if not trace:
            return None

        # 查步骤明细
        steps_stmt = (
            select(AgentTraceStep)
            .where(AgentTraceStep.trace_id == trace_id)
            .order_by(AgentTraceStep.iteration)
        )
        steps_result = await self.db.execute(steps_stmt)
        steps = steps_result.scalars().all()

        return {
            "trace": self._serialize_trace(trace),
            "steps": [self._serialize_step(s) for s in steps],
        }

    async def list_traces(
        self,
        user_id: int | None = None,
        conversation_id: int | None = None,
        execution_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        """列出轨迹（分页）。"""
        conditions = []
        if user_id:
            conditions.append(AgentTrace.user_id == user_id)
        if conversation_id:
            conditions.append(AgentTrace.conversation_id == conversation_id)
        if execution_type:
            conditions.append(AgentTrace.execution_type == execution_type)

        # 总数
        count_stmt = select(func.count(AgentTrace.id)).where(*conditions)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # 分页
        offset = (page - 1) * page_size
        stmt = (
            select(AgentTrace)
            .where(*conditions)
            .order_by(desc(AgentTrace.started_at))
            .offset(offset)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        traces = result.scalars().all()

        return [self._serialize_trace(t) for t in traces], total

    async def get_stats(self, user_id: int | None = None, days: int = 7) -> dict[str, Any]:
        """获取统计摘要。"""
        from datetime import timedelta
        since = datetime.now(timezone.utc) - timedelta(days=days)

        conditions = [AgentTrace.started_at >= since]
        if user_id:
            conditions.append(AgentTrace.user_id == user_id)

        stmt = select(
            func.count(AgentTrace.id).label("total_traces"),
            func.avg(AgentTrace.duration_ms).label("avg_duration_ms"),
            func.sum(AgentTrace.total_input_tokens).label("total_input_tokens"),
            func.sum(AgentTrace.total_output_tokens).label("total_output_tokens"),
            func.avg(AgentTrace.total_iterations).label("avg_iterations"),
            func.sum(AgentTrace.tools_count).label("total_tool_calls"),
            func.sum(AgentTrace.tools_failed).label("total_tool_failures"),
        ).where(*conditions)

        result = await self.db.execute(stmt)
        row = result.one()

        return {
            "period_days": days,
            "total_traces": row.total_traces or 0,
            "avg_duration_ms": round(float(row.avg_duration_ms or 0), 1),
            "total_input_tokens": row.total_input_tokens or 0,
            "total_output_tokens": row.total_output_tokens or 0,
            "avg_iterations": round(float(row.avg_iterations or 0), 2),
            "total_tool_calls": row.total_tool_calls or 0,
            "total_tool_failures": row.total_tool_failures or 0,
            "tool_failure_rate": round(
                (row.total_tool_failures or 0) / max(row.total_tool_calls or 1, 1) * 100, 1
            ),
        }

    def _serialize_trace(self, trace: AgentTrace) -> dict:
        return {
            "id": trace.id,
            "trace_id": trace.trace_id,
            "user_id": trace.user_id,
            "conversation_id": trace.conversation_id,
            "query": trace.query,
            "execution_type": trace.execution_type,
            "model_id": trace.model_id,
            "exit_reason": trace.exit_reason,
            "final_answer": trace.final_answer,
            "total_iterations": trace.total_iterations,
            "total_input_tokens": trace.total_input_tokens,
            "total_output_tokens": trace.total_output_tokens,
            "duration_ms": trace.duration_ms,
            "quality_score": trace.quality_score,
            "tools_count": trace.tools_count,
            "tools_failed": trace.tools_failed,
            "memory_used": trace.memory_used,
            "error": trace.error,
            "started_at": trace.started_at.isoformat() if trace.started_at else None,
            "completed_at": trace.completed_at.isoformat() if trace.completed_at else None,
        }

    def _serialize_step(self, step: AgentTraceStep) -> dict:
        return {
            "iteration": step.iteration,
            "thought": step.thought,
            "action": step.action,
            "action_input": step.action_input,
            "observation": step.observation,
            "is_final": step.is_final,
            "duration_ms": step.duration_ms,
            "input_tokens": step.input_tokens,
            "output_tokens": step.output_tokens,
            "tool_success": step.tool_success,
            "tool_error": step.tool_error,
        }
