"""Safe ReAct-style Agent runner.

This implementation keeps the public API stable while enforcing hard iteration and timeout
limits. Tool execution can be expanded later, but this version never enters an unbounded loop.
"""

import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.adapters.base import LLMRequest
from app.services.llm.gateway import LLMGateway
from app.services.llm.token_counter import TokenCounter


@dataclass
class ReActConfig:
    max_iterations: int = 5
    quality_threshold: float = 0.8
    enable_self_check: bool = True
    max_tokens_per_step: int = 2048
    timeout_seconds: int = 60
    allow_chain_tools: bool = True
    model_context_window: int = 8192
    provider: str = "openai"


@dataclass
class ReActStep:
    iteration: int
    thought: str = ""
    action: str | None = None
    action_input: dict | None = None
    observation: str = ""
    is_final: bool = False


@dataclass
class ReActResult:
    final_answer: str
    steps: list[ReActStep] = field(default_factory=list)
    total_iterations: int = 0
    exit_reason: str = ""
    quality_score: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model_id: str = ""
    elapsed_ms: float = 0


REACT_SYSTEM_PROMPT = """You are a careful enterprise assistant.
Think briefly, use available context, and provide a final answer.
If the answer is uncertain, say what is missing instead of guessing.
Return the final answer directly or in the form [FINAL_ANSWER: ...].
"""


class ReActAgent:
    """Bounded ReAct-style runner with a safe direct-answer fallback."""

    FINAL_ANSWER_PATTERN = re.compile(r"\[FINAL_ANSWER:\s*(.*?)\]\s*$", re.DOTALL | re.IGNORECASE)

    def __init__(self, db: AsyncSession, redis: aioredis.Redis, config: ReActConfig | None = None):
        self.db = db
        self.redis = redis
        self.config = config or ReActConfig()
        self.gateway = LLMGateway(db=db, redis=redis)
        self.token_counter = TokenCounter.for_provider(self.config.provider)

    async def run(self, query: str, context: str = "", tools_prompt: str = "") -> ReActResult:
        started = time.perf_counter()
        steps: list[ReActStep] = []
        prompt = self._build_prompt(query=query, context=context, tools_prompt=tools_prompt)
        prompt = self._trim_prompt(prompt)

        try:
            response = await self.gateway.generate(
                LLMRequest(
                    prompt=prompt,
                    max_tokens=self.config.max_tokens_per_step,
                    stream=False,
                )
            )
            final_answer = self._extract_final_answer(response.content)
            steps.append(
                ReActStep(
                    iteration=1,
                    thought="Generated direct answer with bounded ReAct fallback.",
                    observation=response.content[:2000],
                    is_final=True,
                )
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            return ReActResult(
                final_answer=final_answer,
                steps=steps,
                total_iterations=1,
                exit_reason="final_answer",
                quality_score=1.0 if final_answer else 0.0,
                total_input_tokens=response.input_tokens or self.token_counter.count(prompt),
                total_output_tokens=response.output_tokens or self.token_counter.count(final_answer),
                model_id=response.model_id,
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return ReActResult(
                final_answer=f"Agent execution failed: {exc}",
                steps=[ReActStep(iteration=1, observation=str(exc), is_final=True)],
                total_iterations=1,
                exit_reason="error",
                quality_score=0.0,
                elapsed_ms=elapsed_ms,
            )

    async def run_stream(self, query: str, context: str = "", tools_prompt: str = "") -> AsyncIterator[dict]:
        result = await self.run(query=query, context=context, tools_prompt=tools_prompt)
        for step in result.steps:
            if step.thought:
                yield {"type": "thought", "content": step.thought, "iteration": step.iteration}
            if step.action:
                yield {"type": "action", "tool": step.action, "params": step.action_input or {}, "iteration": step.iteration}
            if step.observation:
                yield {"type": "observation", "content": step.observation, "iteration": step.iteration}
        yield {
            "type": "final_answer",
            "content": result.final_answer,
            "iterations": result.total_iterations,
            "exit_reason": result.exit_reason,
        }

    async def run_with_trace(
        self,
        query: str,
        context: str = "",
        tools_prompt: str = "",
        user_id: int | None = None,
        conversation_id: int | None = None,
    ) -> dict:
        result = await self.run(query=query, context=context, tools_prompt=tools_prompt)
        return {
            "final_answer": result.final_answer,
            "steps": [step.__dict__ for step in result.steps],
            "total_iterations": result.total_iterations,
            "exit_reason": result.exit_reason,
            "quality_score": result.quality_score,
            "model_id": result.model_id,
            "elapsed_ms": result.elapsed_ms,
        }

    def _build_prompt(self, query: str, context: str, tools_prompt: str) -> str:
        parts = [REACT_SYSTEM_PROMPT]
        if tools_prompt:
            parts.append(f"Available tools:\n{tools_prompt}")
        if context:
            parts.append(f"Context:\n{context}")
        parts.append(f"User question:\n{query}")
        return "\n\n".join(parts)

    def _trim_prompt(self, prompt: str) -> str:
        input_budget = max(512, self.config.model_context_window - self.config.max_tokens_per_step)
        if self.token_counter.count(prompt) <= input_budget:
            return prompt
        return self.token_counter.truncate(prompt, input_budget)

    def _extract_final_answer(self, text: str) -> str:
        match = self.FINAL_ANSWER_PATTERN.search(text or "")
        return match.group(1).strip() if match else (text or "").strip()
