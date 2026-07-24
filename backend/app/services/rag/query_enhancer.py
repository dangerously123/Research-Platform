"""
查询增强模块：提升检索召回率的高级策略。

策略包括：
1. HyDE（假设文档嵌入）：让 LLM 生成假设性答案，用答案的嵌入去检索
2. 查询分解：将复杂问题拆解为多个子查询
3. 上下文感知改写：结合对话历史改写当前查询
"""

import re
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.services.llm.adapters.base import LLMRequest
from app.services.llm.gateway import LLMGateway


class QueryEnhancer:
    """
    查询增强器。
    根据问题复杂度选择合适的增强策略。
    """

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def enhance(
        self,
        query: str,
        conversation_history: list[dict] | None = None,
    ) -> list[str]:
        """
        增强查询，返回多个检索变体。
        对简单问题：直接返回原始 + 关键词版
        对复杂问题：尝试 HyDE + 分解

        Returns:
            增强后的查询列表（用于多路召回）
        """
        variants = [query]

        # 1. 上下文感知改写（如果有对话历史）
        if conversation_history:
            rewritten = self._context_aware_rewrite(query, conversation_history)
            if rewritten and rewritten != query:
                variants.append(rewritten)

        # 2. 判断是否为复杂查询
        if self._is_complex_query(query):
            # 分解为子查询
            sub_queries = self._decompose_query(query)
            variants.extend(sub_queries)
        else:
            # 简单查询：生成假设性答案片段
            hypothetical = self._generate_hypothetical_snippet(query)
            if hypothetical:
                variants.append(hypothetical)

        return variants[:5]  # 最多5个变体

    async def hyde_enhance(self, query: str) -> str | None:
        """
        HyDE 策略（轻量版）：
        让 LLM 生成一个假设性的答案片段，
        用这个答案的嵌入去检索（通常比问题本身的嵌入更接近实际文档）。

        注意：这会消耗一次 LLM 调用，仅对重要查询使用。
        """
        try:
            gateway = LLMGateway(db=self.db, redis=self.redis)
            prompt = (
                f"请为以下问题写一段简短的假设性答案（50-100字），"
                f"像是从企业内部文档中摘取的片段：\n\n"
                f"问题：{query}\n\n"
                f"假设性答案片段："
            )
            response = await gateway.generate(
                LLMRequest(prompt=prompt, max_tokens=150, stream=False)
            )
            if response.content and len(response.content) > 20:
                return response.content.strip()
        except Exception:
            pass
        return None

    def _context_aware_rewrite(
        self, query: str, history: list[dict]
    ) -> str | None:
        """
        上下文感知改写：解决代词指代问题。
        例如：
          用户: "Q3销售数据是多少？"
          用户: "环比呢？" → 改写为 "Q3销售数据的环比变化"
        """
        if not history:
            return None

        # 检查是否包含指代词（需要上下文）
        reference_words = ["它", "这个", "那个", "上面", "之前", "刚才", "呢", "也"]
        has_reference = any(w in query for w in reference_words)

        # 检查是否过于简短（可能依赖上下文）
        is_short = len(query) < 8

        if not has_reference and not is_short:
            return None

        # 从最近的用户消息中提取主题
        recent_topic = ""
        for msg in reversed(history[-6:]):
            if msg.get("role") == "user":
                recent_topic = msg.get("content", "")
                break

        if not recent_topic:
            return None

        # 简单策略：将当前查询与上一个问题的主题拼接
        # 实际项目中可用 LLM 做更精准的改写
        topic_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', recent_topic)[:3]
        if topic_keywords:
            return " ".join(topic_keywords) + " " + query

        return None

    def _is_complex_query(self, query: str) -> bool:
        """判断是否为复杂查询（需要分解）。"""
        # 包含"和"、"以及"、"同时"等并列连词
        conjunctions = ["和", "以及", "同时", "还有", "另外", "并且"]
        has_conjunction = any(c in query for c in conjunctions)

        # 问题很长（超过30字）
        is_long = len(query) > 30

        # 包含多个问号
        multi_question = query.count("？") > 1 or query.count("?") > 1

        return (has_conjunction and is_long) or multi_question

    def _decompose_query(self, query: str) -> list[str]:
        """将复杂查询分解为子查询。"""
        sub_queries = []

        # 按连词分割
        parts = re.split(r'[和以及同时还有另外并且，,]', query)
        for part in parts:
            part = part.strip()
            if len(part) >= 5:  # 至少5个字才算有效子查询
                sub_queries.append(part)

        # 按问号分割
        if not sub_queries:
            parts = re.split(r'[？?]', query)
            for part in parts:
                part = part.strip()
                if len(part) >= 5:
                    sub_queries.append(part)

        return sub_queries[:3]

    def _generate_hypothetical_snippet(self, query: str) -> str | None:
        """
        生成假设性文档片段（不调 LLM 的快速版本）。
        基于问题结构转换为陈述句。
        """
        # "怎么/如何 X" → "X 的方法/步骤是"
        match = re.match(r'(?:怎么|如何|怎样)\s*(.+?)[\？?]?$', query)
        if match:
            return f"{match.group(1)} 的方法步骤 流程操作指南"

        # "什么是 X" → "X 是指..."
        match = re.match(r'(?:什么是|.+是什么)\s*(.+?)[\？?]?$', query)
        if match:
            return f"{match.group(1)} 定义概念含义说明"

        # "X 在哪" → "X 的位置路径"
        match = re.match(r'(.+?)(?:在哪|在哪里|怎么找)[\？?]?$', query)
        if match:
            return f"{match.group(1)} 位置路径查找方式"

        return None
