"""User long-term memory service."""

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import redis.asyncio as aioredis
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.memory import MemoryRecord


class MemoryVectorStore:
    """Small adapter around the configured vector store."""

    def __init__(self):
        self._collection = None

    async def initialize(self) -> None:
        if self._collection is not None:
            return
        if settings.VECTOR_DB_TYPE == "chromadb":
            import chromadb

            client = chromadb.HttpClient(host=settings.CHROMADB_HOST, port=settings.CHROMADB_PORT)
            self._collection = client.get_or_create_collection(
                name="user_memories",
                metadata={"hnsw:space": "cosine"},
            )

    async def add(self, vector_id: str, embedding: list[float], metadata: dict, document: str) -> None:
        await self.initialize()
        if self._collection is None:
            return
        self._collection.add(ids=[vector_id], embeddings=[embedding], metadatas=[metadata], documents=[document])

    async def search(
        self,
        query_embedding: list[float],
        user_id: int,
        top_k: int = 5,
        min_score: float = 0.7,
    ) -> list[dict]:
        await self.initialize()
        if self._collection is None:
            return []
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"user_id": user_id},
            include=["documents", "metadatas", "distances"],
        )
        memories: list[dict] = []
        ids = results.get("ids", [[]])[0] if results else []
        for index, vector_id in enumerate(ids):
            distance = results.get("distances", [[]])[0][index] if results.get("distances") else 0
            score = 1 - distance
            if score < min_score:
                continue
            memories.append(
                {
                    "vector_id": vector_id,
                    "score": score,
                    "document": results.get("documents", [[]])[0][index] if results.get("documents") else "",
                    "metadata": results.get("metadatas", [[]])[0][index] if results.get("metadatas") else {},
                }
            )
        return memories

    async def delete(self, vector_ids: list[str]) -> None:
        await self.initialize()
        if self._collection is not None and vector_ids:
            self._collection.delete(ids=vector_ids)

    async def delete_by_user(self, user_id: int) -> None:
        await self.initialize()
        if self._collection is not None:
            self._collection.delete(where={"user_id": user_id})


class EmbeddingService:
    """Lazy sentence-transformer embedding service."""

    def __init__(self):
        self._model = None

    def _load_model(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)

    def encode(self, text: str) -> list[float]:
        self._load_model()
        return self._model.encode(text, normalize_embeddings=True).tolist()


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
    """Manage user memories and semantic recall."""

    MAX_MEMORIES_PER_USER = 500
    MIN_QUESTION_LENGTH = 10
    DUPLICATE_THRESHOLD = 0.95
    RECALL_MIN_SCORE = 0.7
    RECALL_TOP_K = 3
    DECAY_DAYS = 90
    DECAY_FACTOR = 0.9

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self.vector_store = get_memory_vector_store()
        self.embedding = get_embedding_service()

    async def save_memory(
        self,
        user_id: int,
        question: str,
        answer: str,
        conversation_id: int | None = None,
        message_id: int | None = None,
    ) -> MemoryRecord | None:
        if not self._is_worth_remembering(question, answer):
            return None
        if await self._is_duplicate(user_id, question):
            return None

        answer_summary = self._generate_summary(answer)
        key_facts = self._extract_key_facts(answer)
        topic_tags = self._extract_topics(question)
        importance = self._calculate_initial_importance(question, answer)
        vector_id = f"mem_{user_id}_{uuid4().hex}"
        document = f"Question: {question}\nAnswer: {answer_summary}"
        embedding = self.embedding.encode(document)

        await self.vector_store.add(
            vector_id=vector_id,
            embedding=embedding,
            metadata={"user_id": user_id, "topic_tags": topic_tags},
            document=document,
        )

        record = MemoryRecord(
            user_id=user_id,
            question=question,
            answer_summary=answer_summary,
            key_facts=key_facts,
            topic_tags=topic_tags,
            importance=importance,
            access_count=0,
            vector_id=vector_id,
            conversation_id=conversation_id,
            source_message_id=message_id,
        )
        self.db.add(record)
        await self.db.flush()
        await self._check_capacity(user_id)
        return record

    async def recall(
        self,
        user_id: int,
        query: str,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[dict]:
        query_embedding = self.embedding.encode(query)
        results = await self.vector_store.search(
            query_embedding=query_embedding,
            user_id=user_id,
            top_k=top_k or self.RECALL_TOP_K,
            min_score=min_score if min_score is not None else self.RECALL_MIN_SCORE,
        )
        if not results:
            return []

        vector_ids = [item["vector_id"] for item in results]
        db_result = await self.db.execute(
            select(MemoryRecord).where(MemoryRecord.vector_id.in_(vector_ids), MemoryRecord.is_active == True)
        )
        records = {record.vector_id: record for record in db_result.scalars().all()}
        memories: list[dict] = []
        for item in results:
            record = records.get(item["vector_id"])
            if not record:
                continue
            record.access_count += 1
            record.last_accessed_at = datetime.now(timezone.utc)
            record.importance = min(1.0, record.importance + 0.05)
            memories.append(
                {
                    "memory_id": record.id,
                    "question": record.question,
                    "answer_summary": record.answer_summary,
                    "key_facts": record.key_facts,
                    "score": item["score"],
                    "topic_tags": record.topic_tags,
                    "importance": record.importance,
                    "created_at": record.created_at,
                }
            )
        await self.db.flush()
        memories.sort(key=lambda memory: memory["score"] * memory["importance"], reverse=True)
        return memories

    def format_memory_context(self, memories: list[dict]) -> str:
        parts = []
        for memory in memories:
            created_at = memory.get("created_at")
            days_ago = 0
            if created_at:
                days_ago = (datetime.now(timezone.utc) - created_at.replace(tzinfo=timezone.utc)).days
            time_label = f"{days_ago} days ago" if days_ago > 0 else "today"
            parts.append(f"- [{time_label}] Q: {memory['question'][:80]} -> {memory['answer_summary'][:150]}")
        return "\n".join(parts)

    async def decay_memories(self) -> int:
        threshold_date = datetime.now(timezone.utc) - timedelta(days=self.DECAY_DAYS)
        result = await self.db.execute(
            select(MemoryRecord).where(MemoryRecord.is_active == True, MemoryRecord.last_accessed_at < threshold_date)
        )
        count = 0
        for record in result.scalars().all():
            record.importance *= self.DECAY_FACTOR
            if record.importance < 0.1:
                record.is_active = False
            count += 1
        await self.db.flush()
        return count

    async def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(select(MemoryRecord).where(MemoryRecord.expires_at != None, MemoryRecord.expires_at < now))
        records = result.scalars().all()
        vector_ids = [record.vector_id for record in records]
        await self.vector_store.delete(vector_ids)
        for record in records:
            await self.db.delete(record)
        await self.db.flush()
        return len(records)

    async def get_user_memories(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        topic: str | None = None,
    ) -> tuple[list[MemoryRecord], int]:
        conditions = [MemoryRecord.user_id == user_id, MemoryRecord.is_active == True]
        if topic:
            conditions.append(MemoryRecord.topic_tags.contains(topic))
        total = (await self.db.execute(select(func.count(MemoryRecord.id)).where(*conditions))).scalar() or 0
        result = await self.db.execute(
            select(MemoryRecord)
            .where(*conditions)
            .order_by(desc(MemoryRecord.importance), desc(MemoryRecord.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def delete_memory(self, user_id: int, memory_id: int) -> bool:
        result = await self.db.execute(
            select(MemoryRecord).where(MemoryRecord.id == memory_id, MemoryRecord.user_id == user_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return False
        await self.vector_store.delete([record.vector_id])
        await self.db.delete(record)
        await self.db.flush()
        return True

    async def clear_all_memories(self, user_id: int) -> int:
        await self.vector_store.delete_by_user(user_id)
        result = await self.db.execute(delete(MemoryRecord).where(MemoryRecord.user_id == user_id))
        await self.db.flush()
        return result.rowcount or 0

    def _is_worth_remembering(self, question: str, answer: str) -> bool:
        if len(question.strip()) < self.MIN_QUESTION_LENGTH:
            return False
        if len(answer.strip()) < 20:
            return False
        no_result_markers = ["not found", "cannot answer", "no related", "unable to answer"]
        return not any(marker in answer[:100].lower() for marker in no_result_markers)

    async def _is_duplicate(self, user_id: int, question: str) -> bool:
        fingerprint = hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()
        cache_key = f"memory:dedupe:{user_id}:{fingerprint}"
        if await self.redis.get(cache_key):
            return True
        query_embedding = self.embedding.encode(question)
        results = await self.vector_store.search(query_embedding, user_id=user_id, top_k=1, min_score=self.DUPLICATE_THRESHOLD)
        if results:
            await self.redis.setex(cache_key, 3600, "1")
            return True
        return False

    def _generate_summary(self, answer: str) -> str:
        clean = answer.strip()
        return clean if len(clean) <= 200 else clean[:197] + "..."

    def _extract_key_facts(self, answer: str) -> list[str]:
        facts: list[str] = []
        for line in answer.split("\n"):
            line = line.strip()
            if line.startswith("- ") or (len(line) > 2 and line[0].isdigit() and line[1] in ".、"):
                fact = line.lstrip("- 0123456789.、")
                if 5 < len(fact) < 100:
                    facts.append(fact)
        return facts[:10]

    def _extract_topics(self, question: str) -> str:
        topic_keywords = {
            "sales": "sales",
            "revenue": "sales",
            "data": "data_analysis",
            "report": "data_analysis",
            "deploy": "ops",
            "server": "ops",
            "permission": "permission",
            "role": "permission",
            "process": "process",
            "api": "tech",
            "code": "tech",
        }
        lowered = question.lower()
        tags = {tag for keyword, tag in topic_keywords.items() if keyword in lowered}
        return ",".join(sorted(tags)) if tags else "general"

    def _calculate_initial_importance(self, question: str, answer: str) -> float:
        score = 0.5
        if len(question) > 50:
            score += 0.1
        if len(answer) > 300:
            score += 0.1
        score += min(0.2, len(self._extract_key_facts(answer)) * 0.04)
        return min(1.0, score)

    async def _check_capacity(self, user_id: int) -> None:
        count = (
            await self.db.execute(
                select(func.count(MemoryRecord.id)).where(MemoryRecord.user_id == user_id, MemoryRecord.is_active == True)
            )
        ).scalar() or 0
        if count <= self.MAX_MEMORIES_PER_USER:
            return
        overflow = count - self.MAX_MEMORIES_PER_USER
        result = await self.db.execute(
            select(MemoryRecord)
            .where(MemoryRecord.user_id == user_id, MemoryRecord.is_active == True)
            .order_by(MemoryRecord.importance)
            .limit(overflow)
        )
        records = result.scalars().all()
        await self.vector_store.delete([record.vector_id for record in records])
        for record in records:
            await self.db.delete(record)
        await self.db.flush()
