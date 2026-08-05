"""Conversation management service."""

from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import LLMConversation, LLMMessage
from app.services.llm.token_counter import TokenCounter


class ConversationManager:
    """Manage conversation lifecycle, messages, and prompt context."""

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self._token_counter = TokenCounter.default()

    async def create_conversation(self, user_id: int, title: str | None = None) -> LLMConversation:
        conversation = LLMConversation(user_id=user_id, title=title, status="active")
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def get_conversation(self, conversation_id: int, user_id: int) -> LLMConversation | None:
        result = await self.db.execute(
            select(LLMConversation).where(
                LLMConversation.id == conversation_id,
                LLMConversation.user_id == user_id,
                LLMConversation.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        model_id: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        sources: list[dict] | None = None,
        relevance_score: float | None = None,
    ) -> LLMMessage:
        message = LLMMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            sources=sources,
            relevance_score=relevance_score,
        )
        self.db.add(message)
        await self.db.flush()
        values = {
            "total_input_tokens": LLMConversation.total_input_tokens + input_tokens,
            "total_output_tokens": LLMConversation.total_output_tokens + output_tokens,
            "last_active_at": datetime.now(timezone.utc),
        }
        if model_id:
            values["model_id"] = model_id
        await self.db.execute(update(LLMConversation).where(LLMConversation.id == conversation_id).values(**values))
        await self._update_context_cache(conversation_id, role, content)
        return message

    async def build_prompt_context_with_memory(
        self,
        conversation_id: int,
        user_id: int,
        current_query: str,
        model_max_tokens: int = 4096,
    ) -> tuple[list[dict], str]:
        messages = await self.build_prompt_context(conversation_id, model_max_tokens)
        memory_context = ""
        try:
            from app.services.llm.memory import MemoryService

            memory_service = MemoryService(db=self.db, redis=self.redis)
            memories = await memory_service.recall(user_id, current_query)
            memory_context = memory_service.format_memory_context(memories) if memories else ""
        except Exception:
            memory_context = ""
        return messages, memory_context

    async def build_prompt_with_budget(
        self,
        conversation_id: int,
        user_id: int,
        current_query: str,
        system_prompt: str,
        model_context_window: int = 8192,
        max_output_tokens: int = 4096,
        provider: str = "openai",
        tools_prompt: str = "",
        rag_docs: str = "",
        file_context: str = "",
    ):
        from dataclasses import dataclass

        @dataclass
        class AllocationResult:
            prompt: str
            prompt_tokens: int
            available_output_tokens: int
            truncated: bool = False

        context_messages = await self.build_prompt_context(conversation_id, model_context_window)
        history = self._format_messages_as_text(context_messages)
        parts = [system_prompt]
        if tools_prompt:
            parts.append(f"Available tools:\n{tools_prompt}")
        if rag_docs:
            parts.append(f"Retrieved documents:\n{rag_docs}")
        if file_context:
            parts.append(f"Attached file context:\n{file_context}")
        if history:
            parts.append(f"Conversation history:\n{history}")
        parts.append(f"User question:\n{current_query}")
        prompt = "\n\n".join(part for part in parts if part)
        token_count = self._token_counter.count(prompt)
        max_prompt_tokens = max(512, model_context_window - max_output_tokens)
        truncated = False
        if token_count > max_prompt_tokens:
            prompt = prompt[-max_prompt_tokens * 4 :]
            token_count = self._token_counter.count(prompt)
            truncated = True
        return AllocationResult(
            prompt=prompt,
            prompt_tokens=token_count,
            available_output_tokens=max(256, min(max_output_tokens, model_context_window - token_count)),
            truncated=truncated,
        )

    async def build_prompt_context(self, conversation_id: int, model_max_tokens: int = 4096) -> list[dict]:
        messages = await self._get_raw_messages(conversation_id)
        if self._estimate_tokens(messages) <= model_max_tokens:
            return messages
        return await self._compress_context(messages)

    async def get_conversation_history(
        self,
        conversation_id: int,
        page: int = 1,
        page_size: int = 100,
    ) -> list[LLMMessage]:
        result = await self.db.execute(
            select(LLMMessage)
            .where(LLMMessage.conversation_id == conversation_id)
            .order_by(LLMMessage.created_at)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all())

    async def end_conversation(self, conversation_id: int) -> None:
        await self.db.execute(update(LLMConversation).where(LLMConversation.id == conversation_id).values(status="archived"))
        await self.db.flush()

    async def delete_conversation(self, conversation_id: int) -> None:
        await self.db.execute(update(LLMConversation).where(LLMConversation.id == conversation_id).values(status="deleted"))
        await self.redis.delete(f"conv:ctx:{conversation_id}")
        await self.db.flush()

    async def archive_inactive_conversations(self) -> int:
        threshold = datetime.now(timezone.utc) - timedelta(days=30)
        result = await self.db.execute(
            update(LLMConversation)
            .where(LLMConversation.status == "active", LLMConversation.last_active_at < threshold)
            .values(status="archived")
        )
        await self.db.flush()
        return result.rowcount or 0

    async def _get_raw_messages(self, conversation_id: int) -> list[dict]:
        result = await self.db.execute(
            select(LLMMessage).where(LLMMessage.conversation_id == conversation_id).order_by(LLMMessage.created_at)
        )
        return [{"role": message.role, "content": message.content} for message in result.scalars().all()]

    async def _update_context_cache(self, conversation_id: int, role: str, content: str) -> None:
        key = f"conv:ctx:{conversation_id}"
        await self.redis.rpush(key, f"{role}:{content[:1000]}")
        await self.redis.ltrim(key, -40, -1)
        await self.redis.expire(key, 86400)

    async def _compress_context(self, messages: list[dict]) -> list[dict]:
        if len(messages) <= 10:
            return messages
        recent_messages = messages[-10:]
        older_messages = messages[:-10]
        summary = self._format_messages_as_summary(older_messages[-10:])
        return [{"role": "system", "content": f"Earlier conversation summary:\n{summary}"}] + recent_messages

    def _format_messages_as_text(self, messages: list[dict]) -> str:
        return "\n".join(f"{message['role']}: {message['content']}" for message in messages)

    def _format_messages_as_summary(self, messages: list[dict]) -> str:
        return "\n".join(f"{message['role']}: {message['content'][:160]}" for message in messages)

    def _estimate_tokens(self, messages: list[dict]) -> int:
        return self._token_counter.count_messages(messages)

