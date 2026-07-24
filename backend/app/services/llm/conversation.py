"""对话管理器：多轮对话上下文、摘要压缩、会话生命周期。"""

import json
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.llm import LLMConversation, LLMMessage


class ConversationManager:
    """
    对话管理器。
    - 管理会话生命周期（创建、归档、删除）
    - 维护多轮对话上下文（最近 20 轮）
    - 上下文窗口超出 Token 限制时进行摘要压缩
    """

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def create_conversation(self, user_id: int, title: str | None = None) -> LLMConversation:
        """创建新对话会话。"""
        conversation = LLMConversation(
            user_id=user_id,
            title=title,
            status="active",
        )
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def get_conversation(self, conversation_id: int, user_id: int) -> LLMConversation | None:
        """获取会话（验证用户归属）。"""
        stmt = select(LLMConversation).where(
            LLMConversation.id == conversation_id,
            LLMConversation.user_id == user_id,
            LLMConversation.status == "active",
        )
        result = await self.db.execute(stmt)
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
        """添加消息到会话。"""
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

        # 更新会话的 Token 统计和活跃时间
        await self.db.execute(
            update(LLMConversation)
            .where(LLMConversation.id == conversation_id)
            .values(
                total_input_tokens=LLMConversation.total_input_tokens + input_tokens,
                total_output_tokens=LLMConversation.total_output_tokens + output_tokens,
                last_active_at=datetime.now(timezone.utc),
                model_id=model_id,
            )
        )

        # 更新 Redis 上下文缓存
        await self._update_context_cache(conversation_id, role, content)

        return message

    async def build_prompt_context_with_memory(
        self,
        conversation_id: int,
        user_id: int,
        current_query: str,
        model_max_tokens: int = 4096,
    ) -> tuple[list[dict], str]:
        """
        构建包含长期记忆的 Prompt 上下文。

        Returns:
            tuple: (conversation_messages, memory_context_string)
        """
        # 获取会话上下文
        messages = await self.build_prompt_context(conversation_id, model_max_tokens)

        # 检索长期记忆
        memory_context = ""
        try:
            from app.services.llm.memory import MemoryService
            memory_service = MemoryService(db=self.db, redis=self.redis)
            memories = await memory_service.recall(user_id, current_query)
            if memories:
                memory_context = memory_service.format_memory_context(memories)
        except Exception:
            # 记忆检索失败不影响正常对话
            pass

        return messages, memory_context

    async def build_prompt_context(
        self, conversation_id: int, model_max_tokens: int = 4096
    ) -> list[dict]:
        """
        构建当前对话的 Prompt 上下文：
        1. 获取最近 20 轮对话历史
        2. 如超出 Token 预算（模型 60%），对早期内容摘要压缩
        3. 返回格式化的消息列表
        """
        max_turns = settings.LLM_CONTEXT_MAX_TURNS

        # 尝试从 Redis 获取缓存的上下文
        cache_key = f"llm:conv:{conversation_id}"
        cached = await self.redis.get(cache_key)
        if cached:
            messages = json.loads(cached)
        else:
            # 从数据库获取最近消息
            stmt = (
                select(LLMMessage)
                .where(LLMMessage.conversation_id == conversation_id)
                .order_by(LLMMessage.created_at.desc())
                .limit(max_turns * 2)  # 每轮 user + assistant
            )
            result = await self.db.execute(stmt)
            db_messages = list(reversed(result.scalars().all()))

            messages = [
                {"role": msg.role, "content": msg.content}
                for msg in db_messages
            ]

            # 缓存到 Redis
            await self.redis.setex(
                cache_key,
                settings.LLM_CONVERSATION_ARCHIVE_HOURS * 3600,
                json.dumps(messages),
            )

        # 检查 Token 预算
        context_budget = int(model_max_tokens * settings.LLM_CONTEXT_TOKEN_RATIO)
        estimated_tokens = self._estimate_tokens(messages)

        if estimated_tokens > context_budget:
            messages = await self._compress_context(messages)

        return messages

    async def end_conversation(self, conversation_id: int) -> None:
        """结束会话，清空上下文缓存。"""
        await self.redis.delete(f"llm:conv:{conversation_id}")
        await self.db.execute(
            update(LLMConversation)
            .where(LLMConversation.id == conversation_id)
            .values(status="archived")
        )

    async def delete_conversation(self, conversation_id: int) -> None:
        """标记会话为已删除。"""
        await self.redis.delete(f"llm:conv:{conversation_id}")
        await self.db.execute(
            update(LLMConversation)
            .where(LLMConversation.id == conversation_id)
            .values(status="deleted")
        )

    async def get_conversation_history(
        self, conversation_id: int, page: int = 1, page_size: int = 50
    ) -> list[LLMMessage]:
        """获取会话历史消息（分页）。"""
        offset = (page - 1) * page_size
        stmt = (
            select(LLMMessage)
            .where(LLMMessage.conversation_id == conversation_id)
            .order_by(LLMMessage.created_at)
            .offset(offset)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def archive_inactive_conversations(self) -> int:
        """归档超过 24 小时未活动的会话（定时任务）。"""
        threshold = datetime.now(timezone.utc) - timedelta(
            hours=settings.LLM_CONVERSATION_ARCHIVE_HOURS
        )
        stmt = (
            update(LLMConversation)
            .where(
                LLMConversation.status == "active",
                LLMConversation.last_active_at < threshold,
            )
            .values(status="archived")
        )
        result = await self.db.execute(stmt)
        return result.rowcount

    async def _update_context_cache(self, conversation_id: int, role: str, content: str) -> None:
        """更新 Redis 上下文缓存。"""
        cache_key = f"llm:conv:{conversation_id}"
        cached = await self.redis.get(cache_key)

        if cached:
            messages = json.loads(cached)
        else:
            messages = []

        messages.append({"role": role, "content": content})

        # 只保留最近 max_turns * 2 条
        max_messages = settings.LLM_CONTEXT_MAX_TURNS * 2
        if len(messages) > max_messages:
            messages = messages[-max_messages:]

        await self.redis.setex(
            cache_key,
            settings.LLM_CONVERSATION_ARCHIVE_HOURS * 3600,
            json.dumps(messages),
        )

    async def _compress_context(self, messages: list[dict]) -> list[dict]:
        """
        上下文压缩策略：
        - 保留最近 5 轮完整对话（10 条消息）
        - 将更早的对话压缩为摘要
        """
        if len(messages) <= 10:
            return messages

        recent_messages = messages[-10:]
        older_messages = messages[:-10]

        # 生成摘要（简单策略：截取前 N 个字符）
        summary_parts = []
        for msg in older_messages:
            role_label = "用户" if msg["role"] == "user" else "助手"
            summary_parts.append(f"{role_label}: {msg['content'][:100]}")

        summary_text = "\n".join(summary_parts[-5:])  # 最多取 5 条摘要
        summary_message = {
            "role": "system",
            "content": f"[对话历史摘要]:\n{summary_text}",
        }

        return [summary_message] + recent_messages

    def _estimate_tokens(self, messages: list[dict]) -> int:
        """估算消息列表的 Token 数（粗略：中文约 2 字符/token）。"""
        total_chars = sum(len(msg["content"]) for msg in messages)
        return total_chars // 2
