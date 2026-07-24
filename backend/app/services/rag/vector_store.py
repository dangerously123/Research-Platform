"""
向量存储层：封装 ChromaDB 操作，支持语义检索 + 关键词检索。

提供：
- add_documents: 文档入库（切分 + 嵌入 + 存储）
- search: 向量语义检索
- keyword_search: 基于元数据的关键词检索
- delete: 删除文档
"""

import re
from datetime import datetime, timezone

from app.core.config import settings
from app.services.llm.memory import get_embedding_service


class DocumentChunker:
    """
    文档切分器。
    将长文档按语义边界切分为适合检索的片段。
    """

    DEFAULT_CHUNK_SIZE = 500       # 每段最大字符数
    DEFAULT_CHUNK_OVERLAP = 80     # 相邻段重叠字符数

    def chunk(
        self,
        text: str,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> list[str]:
        """
        智能切分文档。
        优先按段落/句子边界切分，避免截断语义。
        """
        chunk_size = chunk_size or self.DEFAULT_CHUNK_SIZE
        chunk_overlap = chunk_overlap or self.DEFAULT_CHUNK_OVERLAP

        if len(text) <= chunk_size:
            return [text]

        # 先按段落分割
        paragraphs = re.split(r'\n\s*\n', text)

        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 如果单个段落就超过 chunk_size，按句子再切
            if len(para) > chunk_size:
                sentences = self._split_sentences(para)
                for sent in sentences:
                    if len(current_chunk) + len(sent) + 1 > chunk_size:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        # 重叠：取上一段的尾部
                        if chunk_overlap > 0 and current_chunk:
                            current_chunk = current_chunk[-chunk_overlap:] + " " + sent
                        else:
                            current_chunk = sent
                    else:
                        current_chunk = current_chunk + " " + sent if current_chunk else sent
            else:
                if len(current_chunk) + len(para) + 2 > chunk_size:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    if chunk_overlap > 0 and current_chunk:
                        current_chunk = current_chunk[-chunk_overlap:] + "\n" + para
                    else:
                        current_chunk = para
                else:
                    current_chunk = current_chunk + "\n" + para if current_chunk else para

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        """按句子边界切分（中英文标点）。"""
        # 中文句号、英文句号、问号、感叹号、分号
        sentences = re.split(r'(?<=[。！？；\.\!\?;])\s*', text)
        return [s for s in sentences if s.strip()]


class KnowledgeVectorStore:
    """
    知识库向量存储。
    基于 ChromaDB 实现，支持：
    - 向量语义检索（cosine similarity）
    - 关键词元数据检索
    - 文档管理（增删改）
    """

    COLLECTION_NAME = "knowledge_base"

    def __init__(self):
        self._collection = None
        self._embedding = get_embedding_service()
        self._chunker = DocumentChunker()

    async def initialize(self):
        """初始化 ChromaDB 集合。"""
        if self._collection is not None:
            return

        import chromadb

        client = chromadb.HttpClient(
            host=settings.CHROMADB_HOST,
            port=settings.CHROMADB_PORT,
        )
        self._collection = client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    async def add_documents(
        self,
        doc_id: str,
        title: str,
        content: str,
        department_id: int,
        access_level: str = "public",
        access_roles: list[int] | None = None,
        doc_type: str = "general",
    ) -> int:
        """
        添加文档到知识库。
        自动切分 → 生成嵌入 → 存入向量库。

        Returns:
            实际存入的片段数量
        """
        await self.initialize()

        # 切分文档
        chunks = self._chunker.chunk(content)

        # 批量生成嵌入
        embeddings = self._embedding.encode_batch(chunks)

        # 构建 ID 和元数据
        ids = []
        metadatas = []
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            ids.append(chunk_id)

            # 提取关键词存入元数据（用于关键词检索）
            keywords = self._extract_keywords_for_metadata(chunk)

            metadatas.append({
                "doc_id": doc_id,
                "title": title,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "department_id": department_id,
                "access_level": access_level,
                "access_roles": ",".join(map(str, access_roles)) if access_roles else "",
                "doc_type": doc_type,
                "keywords": keywords,
                "content_length": len(chunk),
                "created_at": int(datetime.now(timezone.utc).timestamp()),
            })

        # 写入 ChromaDB
        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )

        return len(chunks)

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """
        向量语义检索。
        """
        await self.initialize()

        # 生成查询嵌入
        query_embedding = self._embedding.encode(query)

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        return self._format_results(results)

    async def keyword_search(self, keywords: list[str], top_k: int = 10) -> list[dict]:
        """
        关键词检索：在元数据 keywords 字段中搜索。
        ChromaDB 的 where 过滤实现精确匹配。
        """
        await self.initialize()

        if not keywords:
            return []

        # ChromaDB where 过滤：keywords 字段包含任一关键词
        # ChromaDB 不支持复杂文本搜索，用 $contains 近似实现
        all_results = []
        for kw in keywords[:5]:  # 最多取5个关键词分别查询
            try:
                results = self._collection.query(
                    query_texts=[kw],  # 用 ChromaDB 内置的文本嵌入
                    n_results=top_k // 2,
                    where={"keywords": {"$contains": kw}} if len(kw) >= 2 else None,
                    include=["documents", "metadatas", "distances"],
                )
                formatted = self._format_results(results)
                all_results.extend(formatted)
            except Exception:
                # 某些关键词可能触发过滤异常，跳过
                continue

        # 去重（按 id）
        seen_ids = set()
        unique = []
        for r in all_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                unique.append(r)

        # 按分数排序
        unique.sort(key=lambda x: x["score"], reverse=True)
        return unique[:top_k]

    async def delete_document(self, doc_id: str) -> int:
        """删除文档（及其所有片段）。"""
        await self.initialize()

        # 查找该文档的所有 chunk ID
        results = self._collection.get(
            where={"doc_id": doc_id},
            include=[],
        )

        if results and results["ids"]:
            self._collection.delete(ids=results["ids"])
            return len(results["ids"])
        return 0

    async def get_stats(self) -> dict:
        """获取知识库统计信息。"""
        await self.initialize()
        count = self._collection.count()
        return {
            "total_chunks": count,
            "collection_name": self.COLLECTION_NAME,
        }

    def _format_results(self, results: dict) -> list[dict]:
        """格式化 ChromaDB 查询结果。"""
        formatted = []
        if not results or not results["ids"] or not results["ids"][0]:
            return []

        for i, doc_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i] if results.get("distances") else 0
            score = max(0, 1 - distance)  # cosine distance → similarity

            metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
            content = results["documents"][0][i] if results.get("documents") else ""

            # 解析 access_roles
            access_roles_str = metadata.get("access_roles", "")
            access_roles = [int(x) for x in access_roles_str.split(",") if x] if access_roles_str else None

            formatted.append({
                "id": doc_id,
                "content": content,
                "source": metadata.get("title", ""),
                "score": score,
                "department_id": metadata.get("department_id", 0),
                "access_level": metadata.get("access_level", "public"),
                "access_roles": access_roles,
                "metadata": {
                    "doc_type": metadata.get("doc_type"),
                    "chunk_index": metadata.get("chunk_index"),
                    "total_chunks": metadata.get("total_chunks"),
                    "keywords": metadata.get("keywords", ""),
                },
            })

        return formatted

    def _extract_keywords_for_metadata(self, text: str) -> str:
        """从文本中提取关键词存入元数据（用于关键词检索）。"""
        # 提取中文词组（2-4字）
        chinese = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        # 提取英文单词
        english = re.findall(r'[A-Za-z]\w{2,}', text)
        # 提取数字标识（如版本号、编号）
        codes = re.findall(r'[A-Z]{2,}\d+|\d+\.\d+', text)

        # 去重取频率最高的
        all_words = chinese + english + codes
        word_freq = {}
        for w in all_words:
            word_freq[w] = word_freq.get(w, 0) + 1

        # 取频率 top 20 的关键词
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        top_keywords = [w for w, _ in sorted_words[:20]]

        return " ".join(top_keywords)


# 全局单例
_knowledge_store: KnowledgeVectorStore | None = None


def get_knowledge_store() -> KnowledgeVectorStore:
    """获取知识库向量存储单例。"""
    global _knowledge_store
    if _knowledge_store is None:
        _knowledge_store = KnowledgeVectorStore()
    return _knowledge_store
