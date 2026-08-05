"""Observability services for Agent execution traces."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, get_trace_id
from app.models.audit_trace import AgentTrace, AgentTraceStep

logger = get_logger(__name__)


class TraceRecorder:
    """Record Agent execution traces and step details."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._trace: AgentTrace | None = None
        self._trace_id: str = get_trace_id() or uuid4().hex
        self._start_time: float = 0
        self._tools_called: list[dict] = []

    @property
    def trace_id(self) -> str:
        return self._trace_id

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
        self._start_time = time.perf_counter()
        self._trace = AgentTrace(
            trace_id=self.trace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            query=query,
            execution_type=execution_type,
            model_id=model_id,
            files_used=files_used or [],
            prompt_tokens_budget=prompt_tokens_budget,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(self._trace)
        await self.db.flush()
        logger.info(
            "[Trace] Started: type=%s user=%s query=%s",
            execution_type,
            user_id,
            query[:80],
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
        step = AgentTraceStep(
            trace_id=self.trace_id,
            iteration=iteration,
            thought=thought[:2000] if thought else None,
            action=action,
            action_input=action_input,
            observation=observation[:2000] if observation else None,
            is_final=is_final,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_success=tool_success,
            tool_error=tool_error[:512] if tool_error else None,
        )
        self.db.add(step)
        await self.db.flush()

        if action:
            self._tools_called.append(
                {
                    "name": action,
                    "params": action_input,
                    "success": tool_success,
                    "duration_ms": duration_ms,
                    "iteration": iteration,
                }
            )

        logger.info(
            "[Trace] Step %s action=%s success=%s",
            iteration,
            action or "thought_only",
            tool_success,
            extra={"trace_id": self.trace_id, "iteration": iteration},
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
        if not self._trace:
            return

        duration_ms = (time.perf_counter() - self._start_time) * 1000 if self._start_time else 0
        self._trace.final_answer = final_answer[:5000] if final_answer else None
        self._trace.exit_reason = exit_reason or ("error" if error else "completed")
        self._trace.model_id = model_id or self._trace.model_id
        self._trace.total_iterations = total_iterations
        self._trace.total_input_tokens = total_input_tokens
        self._trace.total_output_tokens = total_output_tokens
        self._trace.duration_ms = duration_ms
        self._trace.quality_score = quality_score
        self._trace.memory_used = memory_used
        self._trace.prompt_tokens_actual = prompt_tokens_actual
        self._trace.error = error[:5000] if error else None
        self._trace.completed_at = datetime.now(timezone.utc)
        self._trace.tools_called = self._tools_called
        self._trace.tools_count = len(self._tools_called)
        self._trace.tools_failed = sum(1 for tool in self._tools_called if tool.get("success") is False)
        await self.db.flush()

        log = logger.error if error else logger.info
        log(
            "[Trace] Completed: exit=%s iterations=%s tokens=%s+%s duration=%.0fms tools=%s",
            self._trace.exit_reason,
            total_iterations,
            total_input_tokens,
            total_output_tokens,
            duration_ms,
            self._trace.tools_count,
            extra={"trace_id": self.trace_id},
        )


class TraceQueryService:
    """Query Agent traces and aggregate trace stats."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        result = await self.db.execute(select(AgentTrace).where(AgentTrace.trace_id == trace_id))
        trace = result.scalar_one_or_none()
        if not trace:
            return None

        steps_result = await self.db.execute(
            select(AgentTraceStep).where(AgentTraceStep.trace_id == trace_id).order_by(AgentTraceStep.iteration)
        )
        steps = steps_result.scalars().all()
        return {"trace": self._serialize_trace(trace), "steps": [self._serialize_step(step) for step in steps]}

    async def list_traces(
        self,
        user_id: int | None = None,
        conversation_id: int | None = None,
        execution_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        conditions = []
        if user_id is not None:
            conditions.append(AgentTrace.user_id == user_id)
        if conversation_id is not None:
            conditions.append(AgentTrace.conversation_id == conversation_id)
        if execution_type:
            conditions.append(AgentTrace.execution_type == execution_type)

        total = (await self.db.execute(select(func.count(AgentTrace.id)).where(*conditions))).scalar() or 0
        result = await self.db.execute(
            select(AgentTrace)
            .where(*conditions)
            .order_by(desc(AgentTrace.started_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._serialize_trace(trace) for trace in result.scalars().all()], total

    async def get_stats(self, user_id: int | None = None, days: int = 7) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        conditions = [AgentTrace.started_at >= since]
        if user_id is not None:
            conditions.append(AgentTrace.user_id == user_id)

        result = await self.db.execute(
            select(
                func.count(AgentTrace.id).label("total_traces"),
                func.avg(AgentTrace.duration_ms).label("avg_duration_ms"),
                func.sum(AgentTrace.total_input_tokens).label("total_input_tokens"),
                func.sum(AgentTrace.total_output_tokens).label("total_output_tokens"),
                func.avg(AgentTrace.total_iterations).label("avg_iterations"),
                func.sum(AgentTrace.tools_count).label("total_tool_calls"),
                func.sum(AgentTrace.tools_failed).label("total_tool_failures"),
            ).where(*conditions)
        )
        row = result.one()
        total_tool_calls = row.total_tool_calls or 0
        total_tool_failures = row.total_tool_failures or 0
        return {
            "period_days": days,
            "total_traces": row.total_traces or 0,
            "avg_duration_ms": round(float(row.avg_duration_ms or 0), 1),
            "total_input_tokens": row.total_input_tokens or 0,
            "total_output_tokens": row.total_output_tokens or 0,
            "avg_iterations": round(float(row.avg_iterations or 0), 2),
            "total_tool_calls": total_tool_calls,
            "total_tool_failures": total_tool_failures,
            "tool_failure_rate": round(total_tool_failures / max(total_tool_calls, 1) * 100, 1),
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
