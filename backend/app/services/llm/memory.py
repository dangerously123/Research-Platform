"""
向量记忆服务：用户长期记忆的写入、语义检索、衰减管理。

架构：
- 向量数据存储在 ChromaDB/Milvus（语义检索）
- 元数据存储在 MySQL memory_records 表（管理展示）
- Redis 缓存热门记忆（加速检索）
"""

import json
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import redis.asyncio as aioredis
from sqlalchemy import select, update, delete, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.memory import MemoryRecord


class MemoryVectorStore:
    """
    记忆向量存储抽象层。
    封装 ChromaDB/Milvus 操作，供 MemoryService 调用。
    """

    def __init__(self):
        self._collection = None

    async def initialize(self):
        """初始化向量集合（懒加载）。"""
        if self._collection is not None:
            return

        if settings.VECTOR_DB_TYPE == "chromadb":
            await self._init_chromadb()
        else:
            await self._init_milvus()

    async def _init_chromadb(self):
        """初始化 ChromaDB 记忆集合。"""
        import chromadb

        client = chromadb.HttpClient(
            host=settings.CHROMADB_HOST,
            port=settings.CHROMADB_PORT,
        )
        self._collection = client.get_or_create_collection(
            name="user_memories",
            metadata={"hnsw:space": "cosine"},
        )

    async def _init_milvus(self):
        """初始化 Milvus 记忆集合（占位，结构同 ChromaDB）。"""
        # Milvus 集成在生产环境中实现
        pass

    async def add(
        self,
        vector_id: str,
        embedding: list[float],
        metadata: dict,
        document: str,
    ) -> None:
        """写入一条记忆向量。"""
        await self.initialize()
        if self._collection is None:
            return

        self._collection.add(
            ids=[vector_id],
            embeddings=[embedding],
            metadatas=[metadata],
            documents=[document],
        )

    async def search(
        self,
        query_embedding: list[float],
        user_id: int,
        top_k: int = 5,
        min_score: float = 0.7,
    ) -> list[dict]:
        """
        语义检索用户记忆。

        Returns:
            [{"vector_id": str, "score": float, "document": str, "metadata": dict}, ...]
        """
        await self.initialize()
        if self._collection is None:
            return []

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"user_id": user_id},
            include=["documents", "metadatas", "distances"],
        )

        memories = []
        if results and results["ids"] and results["ids"][0]:
            for i, vid in enumerate(results["ids"][0]):
                # ChromaDB 返回的是 distance，转为 similarity
                distance = results["distances"][0][i] if results["distances"] else 0
                score = 1 - distance  # cosine distance → similarity

                if score >= min_score:
                    memories.append({
                        "vector_id": vid,
                        "score": score,
                        "document": results["documents"][0][i] if results["documents"] else "",
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    })

        return memories

    async def delete(self, vector_ids: list[str]) -> None:
        """删除指定记忆向量。"""
        await self.initialize()
        if self._collection is None:
            return
        self._collection.delete(ids=vector_ids)

    async def delete_by_user(self, user_id: int) -> None:
        """删除用户的所有记忆向量。"""
        await self.initialize()
        if self._collection is None:
            return
        self._collection.delete(where={"user_id": user_id})


class EmbeddingService:
    """嵌入向量生成服务。"""

    def __init__(self):
        self._model = None

    def _load_model(self):
        """懒加载 Embedding 模型。"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)

    def encode(self, text: str) -> list[float]:
        """将文本编码为嵌入向量。"""
        self._load_model()
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """批量编码。"""
        self._load_model()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()


# 全局单例
_vector_store: MemoryVectorStore | None = None
_embedding_service: EmbeddingService | None = None


def get_memory_vector_store() -> MemoryVectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = MemoryVectorStore()
    return _vector_store


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


class MemoryService:
    """
    用户记忆服务核心。

    职责：
    - 写入记忆：判断是否值得记忆 → 生成摘要 → 嵌入向量 → 存入向量库+MySQL
    - 检索记忆：语义检索 → 相似度过滤 → 按重要性排序 → 返回相关记忆
    - 衰减管理：定期降低未被引用记忆的重要性，淘汰低价值记忆
    - 用户管理：查看/删除/搜索个人记忆
    """

    # 配置
    MAX_MEMORIES_PER_USER = 500       # 每用户最大记忆数
    MIN_QUESTION_LENGTH = 10          # 最短问题长度（过滤寒暄）
    DUPLICATE_THRESHOLD = 0.95        # 去重阈值
    RECALL_MIN_SCORE = 0.7            # 检索最低相似度
    RECALL_TOP_K = 3                  # 检索返回数量
    DECAY_DAYS = 90                   # 衰减周期（天）
    DECAY_FACTOR = 0.9                # 衰减系数

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self.vector_store = get_memory_vector_store()
        self.embedding = get_embedding_service()

    # ==================== 写入记忆 ====================

    async def save_memory(
        self,
        user_id: int,
        question: str,
        answer: str,
        conversation_id: int | None = None,
        message_id: int | None = None,
    ) -> MemoryRecord | None:
        """
        保存一条记忆。

        流程：
        1. 判断是否值得记忆
        2. 检查是否重复
        3. 生成摘要和关键事实
        4. 嵌入向量并存入向量库
        5. 写入 MySQL 元数据
        6. 容量检查（淘汰低价值记忆）

        Returns:
            MemoryRecord 或 None（如果不值得记忆）
        """
        # 1. 判断是否值得记忆
        if not self._is_worth_remembering(question, answer):
            return None

        # 2. 检查是否重复
        is_dup = await self._is_duplicate(user_id, question)
        if is_dup:
            return None

        # 3. 生成摘要和标签
        answer_summary = self._generate_summary(answer)
        key_facts = self._extract_key_facts(answer)
        topic_tags = self._extract_topics(question)

        # 4. 生成嵌入向量并写入向量库
        memory_text = f"问题: {question}\n回答摘要: {answer_summary}"
        embedding = self.embedding.encode(memory_text)
        vector_id = f"mem_{user_id}_{uuid4().hex[:12]}"

        await self.vector_store.add(
            vector_id=vector_id,
            embedding=embedding,
            metadata={
                "user_id": user_id,
                "question": question[:500],
                "topic_tags": topic_tags,
                "created_at": int(datetime.now(timezone.utc).timestamp()),
            },
            document=memory_text,
        )

        # 5. 写入 MySQL
        record = MemoryRecord(
            user_id=user_id,
            question=question,
            answer_summary=answer_summary,
            key_facts=key_facts,
            topic_tags=topic_tags,
            importance=self._calculate_initial_importance(question, answer),
            vector_id=vector_id,
            conversation_id=conversation_id,
            source_message_id=message_id,
        )
        self.db.add(record)
        await self.db.flush()

        # 6. 容量检查
        await self._check_capacity(user_id)

        return record

    # ==================== 检索记忆 ====================

    async def recall(
        self,
        user_id: int,
        query: str,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[dict]:
        """
        语义检索用户记忆。

        Returns:
            [{"memory_id": int, "question": str, "answer_summary": str,
              "score": float, "topic_tags": str, "created_at": datetime}, ...]
        """
        top_k = top_k or self.RECALL_TOP_K
        min_score = min_score or self.RECALL_MIN_SCORE

        # 嵌入查询
        query_embedding = self.embedding.encode(query)

        # 向量检索
        results = await self.vector_store.search(
            query_embedding=query_embedding,
            user_id=user_id,
            top_k=top_k,
            min_score=min_score,
        )

        if not results:
            return []

        # 获取 MySQL 元数据并更新访问计数
        vector_ids = [r["vector_id"] for r in results]
        stmt = (
            select(MemoryRecord)
            .where(
                MemoryRecord.vector_id.in_(vector_ids),
                MemoryRecord.is_active == True,
            )
        )
        db_result = await self.db.execute(stmt)
        records = {r.vector_id: r for r in db_result.scalars().all()}

        # 合并结果
        memories = []
        for vec_result in results:
            record = records.get(vec_result["vector_id"])
            if not record:
                continue

            # 更新访问计数
            record.access_count += 1
            record.last_accessed_at = datetime.now(timezone.utc)
            # 提升重要性（被引用说明有价值）
            record.importance = min(1.0, record.importance + 0.05)

            memories.append({
                "memory_id": record.id,
                "question": record.question,
                "answer_summary": record.answer_summary,
                "key_facts": record.key_facts,
                "score": vec_result["score"],
                "topic_tags": record.topic_tags,
                "importance": record.importance,
                "created_at": record.created_at,
            })

        await self.db.flush()

        # 按 score * importance 综合排序
        memories.sort(key=lambda m: m["score"] * m["importance"], reverse=True)
        return memories

    def format_memory_context(self, memories: list[dict]) -> str:
        """
        将检索到的记忆格式化为 Prompt 上下文。
        """
        if not memories:
            return ""

        parts = []
        for mem in memories:
            days_ago = (datetime.now(timezone.utc) - mem["created_at"].replace(tzinfo=timezone.utc)).days
            time_label = f"{days_ago}天前" if days_ago > 0 else "今天"
            parts.append(
                f"- [{time_label}] 用户问过\"{mem['question'][:80]}\" → "
                f"回答要点: {mem['answer_summary'][:150]}"
            )

        return "\n".join(parts)

    # ==================== 衰减管理 ====================

    async def decay_memories(self) -> int:
        """
        定时任务：对长期未被引用的记忆进行衰减。
        超过 DECAY_DAYS 未被访问的记忆，importance 乘以 DECAY_FACTOR。
        importance 降到 0.1 以下的标记为失活。

        Returns:
            受影响的记忆数量
        """
        threshold_date = datetime.now(timezone.utc) - timedelta(days=self.DECAY_DAYS)

        # 查找需要衰减的记忆
        stmt = (
            select(MemoryRecord)
            .where(
                MemoryRecord.is_active == True,
                MemoryRecord.last_accessed_at < threshold_date,
            )
        )
        result = await self.db.execute(stmt)
        records = result.scalars().all()

        count = 0
        for record in records:
            record.importance *= self.DECAY_FACTOR
            count += 1

            # 过低的标记失活
            if record.importance < 0.1:
                record.is_active = False

        await self.db.flush()
        return count

    async def cleanup_expired(self) -> int:
        """清理已过期的记忆。"""
        now = datetime.now(timezone.utc)
        stmt = (
            select(MemoryRecord)
            .where(
                MemoryRecord.expires_at != None,
                MemoryRecord.expires_at < now,
            )
        )
        result = await self.db.execute(stmt)
        expired = result.scalars().all()

        vector_ids = [r.vector_id for r in expired]
        if vector_ids:
            await self.vector_store.delete(vector_ids)

        await self.db.execute(
            delete(MemoryRecord).where(MemoryRecord.vector_id.in_(vector_ids))
        )
        return len(vector_ids)

    # ==================== 用户管理 ====================

    async def get_user_memories(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        topic: str | None = None,
    ) -> tuple[list[MemoryRecord], int]:
        """获取用户记忆列表（分页）。"""
        conditions = [
            MemoryRecord.user_id == user_id,
            MemoryRecord.is_active == True,
        ]
        if topic:
            conditions.append(MemoryRecord.topic_tags.contains(topic))

        # 总数
        count_stmt = select(func.count(MemoryRecord.id)).where(*conditions)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # 分页数据
        offset = (page - 1) * page_size
        stmt = (
            select(MemoryRecord)
            .where(*conditions)
            .order_by(desc(MemoryRecord.importance), desc(MemoryRecord.created_at))
            .offset(offset)
            .limit(page_size)
        )
        result = await self.db.execute(stmt)
        records = list(result.scalars().all())

        return records, total

    async def delete_memory(self, user_id: int, memory_id: int) -> bool:
        """删除指定记忆。"""
        stmt = select(MemoryRecord).where(
            MemoryRecord.id == memory_id,
            MemoryRecord.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return False

        # 从向量库删除
        await self.vector_store.delete([record.vector_id])

        # 从 MySQL 删除
        await self.db.delete(record)
        await self.db.flush()
        return True

    async def clear_all_memories(self, user_id: int) -> int:
        """清空用户所有记忆。"""
        # 从向量库删除
        await self.vector_store.delete_by_user(user_id)

        # 从 MySQL 删除
        stmt = delete(MemoryRecord).where(MemoryRecord.user_id == user_id)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    # ==================== 内部方法 ====================

    def _is_worth_remembering(self, question: str, answer: str) -> bool:
        """判断是否值得存为记忆。"""
        # 问题太短（寒暄类）
        if len(question.strip()) < self.MIN_QUESTION_LENGTH:
            return False
        # 回答太短（可能是错误或无内容）
        if len(answer.strip()) < 20:
            return False
        # 包含无结果提示
        no_result_markers = ["未找到", "无法回答", "没有相关", "无匹配"]
        if any(m in answer[:100] for m in no_result_markers):
            return False
        return True

    async def _is_duplicate(self, user_id: int, question: str) -> bool:
        """检查是否与近期记忆重复。"""
        query_embedding = self.embedding.encode(question)
        results = await self.vector_store.search(
            query_embedding=query_embedding,
            user_id=user_id,
            top_k=1,
            min_score=self.DUPLICATE_THRESHOLD,
        )
        return len(results) > 0

    def _generate_summary(self, answer: str) -> str:
        """生成回答摘要（截取前200字）。"""
        # 简单策略：取前 200 字符
        # 实际项目中可调用 LLM 生成更精炼的摘要
        clean = answer.strip()
        if len(clean) <= 200:
            return clean
        return clean[:197] + "..."

    def _extract_key_facts(self, answer: str) -> list[str]:
        """从回答中提取关键事实。"""
        facts = []
        lines = answer.split("\n")
        for line in lines:
            line = line.strip()
            # 提取列表项
            if line and (line.startswith("- ") or line.startswith("• ") or
                        (len(line) > 2 and line[0].isdigit() and line[1] in ".、")):
                fact = line.lstrip("-•0123456789.、 ")
                if 5 < len(fact) < 100:
                    facts.append(fact)
        return facts[:10]  # 最多 10 条

    def _extract_topics(self, question: str) -> str:
        """从问题中提取主题标签。"""
        # 简单关键词匹配（实际项目可用 NER 或 LLM 提取）
        topic_keywords = {
            "销售": "销售", "营收": "销售", "收入": "销售",
            "数据": "数据分析", "报表": "数据分析", "统计": "数据分析",
            "部署": "运维", "服务器": "运维", "配置": "运维",
            "权限": "权限管理", "角色": "权限管理",
            "流程": "流程", "审批": "流程",
            "API": "技术", "接口": "技术", "代码": "技术", "开发": "技术",
        }
        tags = set()
        for keyword, tag in topic_keywords.items():
            if keyword in question:
                tags.add(tag)
        return ",".join(tags) if tags else "通用"

    def _calculate_initial_importance(self, question: str, answer: str) -> float:
        """计算初始重要性。"""
        score = 0.5  # 基准分

        # 问题越长可能越复杂
        if len(question) > 50:
            score += 0.1
        # 回答越长说明信息量越大
        if len(answer) > 300:
            score += 0.1
        # 包含关键事实越多越重要
        facts = self._extract_key_facts(answer)
        score += min(0.2, len(facts) * 0.04)

        return min(1.0, score)

    async def _check_capacity(self, user_id: int) -> None:
        """容量检查：超过上限时淘汰最低重要性的记忆。"""
        count_stmt = select(func.count(MemoryRecord.id)).where(
            MemoryRecord.user_id == user_id,
            MemoryRecord.is_active == True,
        )
        count = (await self.db.execute(count_stmt)).scalar() or 0

        if count <= self.MAX_MEMORIES_PER_USER:
            return

        # 淘汰 importance 最低的记忆
        overflow = count - self.MAX_MEMORIES_PER_USER
        stmt = (
            select(MemoryRecord)
            .where(MemoryRecord.user_id == user_id, MemoryRecord.is_active == True)
            .order_by(MemoryRecord.importance)
            .limit(overflow)
        )
        result = await self.db.execute(stmt)
        to_remove = result.scalars().all()

        vector_ids = [r.vector_id for r in to_remove]
        if vector_ids:
            await self.vector_store.delete(vector_ids)
            for r in to_remove:
                await self.db.delete(r)
            await self.db.flush()
