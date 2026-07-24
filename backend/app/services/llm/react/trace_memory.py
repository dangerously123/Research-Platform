"""
推理过程记忆（Trace Memory）。

存储成功的推理链路，下次遇到相似问题时：
- 直接复用已验证的工具调用序列
- 跳过"探索"阶段，直接进入"执行"模式
- 大幅减少推理轮数（从5轮降到1-2轮）

设计：
- 每次成功完成 ReAct 后，将推理链路存入向量库
- 新问题到达时，先检索是否有相似的历史链路
- 如果匹配度高，将链路作为"参考路径"注入 Prompt
"""

import json
import re
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.memory import get_embedding_service, get_memory_vector_store


@dataclass
class ReasoningTrace:
    """一条推理链路记录。"""
    query_pattern: str            # 问题模式（泛化后的形式）
    tool_chain: list[dict]        # 工具调用链 [{"tool": name, "param_pattern": {...}}]
    total_steps: int              # 推理总轮数
    success: bool                 # 是否成功
    exit_reason: str              # 退出原因
    quality_score: float          # 最终质量分
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TraceMemoryStore:
    """
    推理链路向量存储。
    使用独立的向量集合存储推理链路模式。
    """

    COLLECTION_NAME = "reasoning_traces"
    CACHE_TTL = 3600  # Redis 缓存1小时

    def __init__(self):
        self._collection = None
        self._embedding = get_embedding_service()

    async def _ensure_collection(self):
        """确保向量集合已创建。"""
        if self._collection is not None:
            return

        from app.core.config import settings
        import chromadb

        try:
            client = chromadb.HttpClient(
                host=settings.CHROMADB_HOST,
                port=settings.CHROMADB_PORT,
            )
            self._collection = client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            # ChromaDB 不可用时静默失败
            pass

    async def save_trace(self, trace: ReasoningTrace) -> str | None:
        """
        保存一条成功的推理链路。

        Returns:
            trace_id 或 None
        """
        if not trace.success or not trace.tool_chain:
            return None

        await self._ensure_collection()
        if self._collection is None:
            return None

        # 生成嵌入
        text = f"问题模式: {trace.query_pattern}\n工具链: {' → '.join(t['tool'] for t in trace.tool_chain)}"
        embedding = self._embedding.encode(text)

        trace_id = f"trace_{hashlib.md5(text.encode()).hexdigest()[:12]}"

        metadata = {
            "query_pattern": trace.query_pattern,
            "tool_chain_json": json.dumps(trace.tool_chain, ensure_ascii=False),
            "total_steps": trace.total_steps,
            "exit_reason": trace.exit_reason,
            "quality_score": trace.quality_score,
            "usage_count": 0,
            "created_at": int(trace.created_at.timestamp()),
        }

        try:
            self._collection.upsert(
                ids=[trace_id],
                embeddings=[embedding],
                documents=[text],
                metadatas=[metadata],
            )
            return trace_id
        except Exception:
            return None

    async def find_similar_trace(
        self, query: str, min_score: float = 0.75
    ) -> dict | None:
        """
        检索与当前查询相似的历史推理链路。

        Returns:
            {"trace_id": str, "tool_chain": [...], "score": float, "query_pattern": str}
            或 None
        """
        await self._ensure_collection()
        if self._collection is None:
            return None

        embedding = self._embedding.encode(query)

        try:
            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=3,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return None

        if not results or not results["ids"] or not results["ids"][0]:
            return None

        # 取最相似的一条
        for i, trace_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            score = 1 - distance

            if score >= min_score:
                metadata = results["metadatas"][0][i]
                tool_chain = json.loads(metadata.get("tool_chain_json", "[]"))

                return {
                    "trace_id": trace_id,
                    "tool_chain": tool_chain,
                    "score": score,
                    "query_pattern": metadata.get("query_pattern", ""),
                    "total_steps": metadata.get("total_steps", 0),
                    "quality_score": metadata.get("quality_score", 0),
                }

        return None

    async def increment_usage(self, trace_id: str) -> None:
        """记录链路被复用的次数。"""
        await self._ensure_collection()
        if self._collection is None:
            return

        try:
            result = self._collection.get(ids=[trace_id], include=["metadatas"])
            if result and result["metadatas"]:
                metadata = result["metadatas"][0]
                metadata["usage_count"] = metadata.get("usage_count", 0) + 1
                self._collection.update(ids=[trace_id], metadatas=[metadata])
        except Exception:
            pass


class TraceMemory:
    """
    推理过程记忆服务。

    职责：
    1. ReAct 成功后 → 提取并存储推理链路
    2. 新问题到达时 → 检索相似链路
    3. 如果匹配到 → 生成"参考路径"注入 Prompt
    """

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.store = TraceMemoryStore()

    async def save_successful_trace(
        self,
        query: str,
        steps: list,  # ReActStep list
        exit_reason: str,
        quality_score: float,
    ) -> str | None:
        """
        在 ReAct 成功完成后调用。
        提取推理链路模式并存储。
        """
        # 只存储成功且有工具调用的链路
        tool_steps = [s for s in steps if s.action]
        if not tool_steps:
            return None

        # 泛化查询模式（将具体数字/名称替换为占位符）
        query_pattern = self._generalize_query(query)

        # 提取工具链
        tool_chain = []
        for step in tool_steps:
            chain_entry = {
                "tool": step.action,
                "param_pattern": self._generalize_params(step.action_input or {}),
                "iteration": step.iteration,
            }
            tool_chain.append(chain_entry)

        trace = ReasoningTrace(
            query_pattern=query_pattern,
            tool_chain=tool_chain,
            total_steps=len(steps),
            success=True,
            exit_reason=exit_reason,
            quality_score=quality_score,
        )

        return await self.store.save_trace(trace)

    async def recall_trace(self, query: str) -> dict | None:
        """
        检索是否有可复用的历史推理链路。

        Returns:
            {"tool_chain": [...], "guidance": str, "score": float} 或 None
        """
        # 先检查 Redis 缓存
        cache_key = f"trace:recall:{hashlib.md5(query.encode()).hexdigest()[:12]}"
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)

        # 向量检索
        result = await self.store.find_similar_trace(query, min_score=0.75)
        if not result:
            return None

        # 生成引导文本
        guidance = self._format_trace_guidance(result)

        output = {
            "tool_chain": result["tool_chain"],
            "guidance": guidance,
            "score": result["score"],
            "trace_id": result["trace_id"],
        }

        # 缓存
        await self.redis.setex(cache_key, TraceMemoryStore.CACHE_TTL, json.dumps(output))

        # 记录使用
        await self.store.increment_usage(result["trace_id"])

        return output

    def _format_trace_guidance(self, trace_result: dict) -> str:
        """格式化链路为 Prompt 引导。"""
        chain = trace_result["tool_chain"]
        score = trace_result["score"]
        pattern = trace_result.get("query_pattern", "")

        lines = [
            f"[历史推理参考] 相似度:{score:.0%}",
            f"相似问题模式: {pattern}",
            f"参考工具调用链路（共{len(chain)}步）：",
        ]
        for i, step in enumerate(chain, 1):
            params_hint = ", ".join(f"{k}=<{v}>" for k, v in step.get("param_pattern", {}).items())
            lines.append(f"  步骤{i}: {step['tool']}({params_hint})")

        lines.append("")
        lines.append("你可以参考此链路，但需要根据当前问题的具体数值调整参数。")
        lines.append("如果当前问题与参考不完全匹配，请自行判断。")

        return "\n".join(lines)

    def _generalize_query(self, query: str) -> str:
        """
        泛化查询：将具体值替换为模式占位符。
        "北京到上海多远" → "{城市}到{城市}多远"
        "计算 3.14*25" → "计算 {数字}*{数字}"
        """
        result = query

        # 替换日期
        result = re.sub(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', '{日期}', result)
        # 替换数字
        result = re.sub(r'\d+\.?\d*', '{数字}', result)
        # 替换城市名（常见城市）
        cities = "北京|上海|广州|深圳|杭州|成都|武汉|南京|西安|重庆|天津|苏州|长沙|郑州"
        result = re.sub(f'({cities})', '{城市}', result)

        return result

    def _generalize_params(self, params: dict) -> dict:
        """
        泛化参数：将具体值替换为类型描述。
        {"city1": "北京", "city2": "上海"} → {"city1": "城市名", "city2": "城市名"}
        """
        generalized = {}
        for key, value in params.items():
            if isinstance(value, (int, float)):
                generalized[key] = "数字"
            elif isinstance(value, str):
                if re.match(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', value):
                    generalized[key] = "日期"
                elif len(value) <= 4 and re.match(r'^[\u4e00-\u9fff]+$', value):
                    generalized[key] = "名称"
                else:
                    generalized[key] = "文本"
            elif isinstance(value, list):
                generalized[key] = "列表"
            else:
                generalized[key] = "值"
        return generalized
