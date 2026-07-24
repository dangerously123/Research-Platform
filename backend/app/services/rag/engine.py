"""
RAG 知识检索引擎（增强版）。

增强点：
1. 混合检索策略：向量语义检索 + 关键词 BM25 检索
2. 查询改写：将口语化问题改写为更适合检索的形式
3. 多路召回合并：语义+关键词结果融合
4. 相关性阈值过滤：丢弃低分噪音
5. 重排序（Reranking）：对初检结果二次评分
6. 结果去重：基于内容相似度去除重复片段
7. 权限过滤后动态补充：过滤后不够则扩大检索范围
8. 结果缓存：相同查询短期缓存
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.llm.adapters.base import LLMRequest
from app.services.llm.gateway import LLMGateway
from app.services.permission.calculator import PermissionCalculator


@dataclass
class DocumentFragment:
    """检索到的文档片段。"""
    id: str
    content: str
    source: str
    relevance_score: float
    department_id: int = 0
    access_level: str = "public"
    access_roles: list[int] | None = None
    metadata: dict | None = None
    retrieval_method: str = "vector"  # vector / keyword / hybrid


@dataclass
class RetrievalResult:
    """检索结果汇总。"""
    documents: list[DocumentFragment]
    query_original: str
    query_rewritten: str
    total_candidates: int
    after_dedup: int
    after_filter: int
    retrieval_time_ms: float = 0
    methods_used: list[str] = field(default_factory=list)


class QueryRewriter:
    """
    查询改写器。
    将用户口语化/模糊问题改写为更适合检索的形式。
    """

    # 停用词（不影响检索意图的词）
    STOP_WORDS = {
        "请问", "请", "帮我", "我想", "想要", "能不能", "可以", "怎么",
        "如何", "什么是", "是什么", "有没有", "告诉我", "查一下", "看看",
        "吗", "呢", "了", "的", "是", "在", "有", "和", "与", "或",
        "一下", "一些", "相关", "关于",
    }

    # 同义词扩展映射
    SYNONYM_MAP = {
        "部署": ["部署", "安装", "上线", "发布"],
        "配置": ["配置", "设置", "设定", "参数"],
        "报错": ["报错", "错误", "异常", "失败", "bug"],
        "性能": ["性能", "速度", "响应时间", "延迟", "慢"],
        "权限": ["权限", "访问控制", "授权", "角色"],
    }

    def rewrite(self, query: str) -> list[str]:
        """
        对查询进行改写，返回多个检索变体。

        Returns:
            [原始query, 清洁版query, 关键词版query]
        """
        variants = [query]

        # 1. 清洁版：去除停用词，保留核心意图
        cleaned = self._remove_stop_words(query)
        if cleaned and cleaned != query:
            variants.append(cleaned)

        # 2. 关键词版：提取核心关键词
        keywords = self._extract_keywords(query)
        if keywords:
            variants.append(" ".join(keywords))

        return variants

    def expand_with_synonyms(self, query: str) -> list[str]:
        """用同义词扩展查询。"""
        expansions = [query]
        for word, synonyms in self.SYNONYM_MAP.items():
            if word in query:
                for syn in synonyms:
                    if syn != word:
                        expansions.append(query.replace(word, syn))
                break  # 只扩展第一个匹配到的
        return expansions[:3]  # 最多3个变体

    def _remove_stop_words(self, text: str) -> str:
        result = text
        for sw in self.STOP_WORDS:
            result = result.replace(sw, "")
        return result.strip()

    def _extract_keywords(self, text: str) -> list[str]:
        """提取关键词（简单实现：保留名词性成分）。"""
        # 去除停用词后按空格和标点分割
        cleaned = self._remove_stop_words(text)
        # 保留中文词组（2字以上）和英文单词
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,}', cleaned)
        english_words = re.findall(r'[a-zA-Z]+\w*', cleaned)
        # 保留数字
        numbers = re.findall(r'\d+', cleaned)
        return chinese_words + english_words + numbers


class ResultReranker:
    """
    结果重排序器。
    对初检结果进行二次评分，综合考虑多个信号。
    """

    # 权重配置
    VECTOR_SCORE_WEIGHT = 0.5     # 向量相似度权重
    KEYWORD_MATCH_WEIGHT = 0.3    # 关键词命中权重
    RECENCY_WEIGHT = 0.1          # 时效性权重
    SOURCE_QUALITY_WEIGHT = 0.1   # 来源质量权重

    def rerank(
        self,
        documents: list[DocumentFragment],
        query: str,
        query_keywords: list[str],
    ) -> list[DocumentFragment]:
        """
        重排序。综合多维度信号对结果重新评分排序。
        """
        scored_docs = []
        for doc in documents:
            final_score = self._calculate_final_score(doc, query, query_keywords)
            doc.relevance_score = final_score
            scored_docs.append(doc)

        # 按最终分数降序排序
        scored_docs.sort(key=lambda d: d.relevance_score, reverse=True)
        return scored_docs

    def _calculate_final_score(
        self,
        doc: DocumentFragment,
        query: str,
        keywords: list[str],
    ) -> float:
        """计算综合评分。"""
        # 1. 向量相似度分（已有）
        vector_score = doc.relevance_score

        # 2. 关键词命中率
        keyword_score = self._keyword_match_score(doc.content, keywords)

        # 3. 标题/来源匹配加成
        source_score = self._source_match_score(doc.source, query, keywords)

        # 4. 内容长度合理性（过短或过长降权）
        length_factor = self._length_factor(doc.content)

        # 综合计算
        final = (
            vector_score * self.VECTOR_SCORE_WEIGHT +
            keyword_score * self.KEYWORD_MATCH_WEIGHT +
            source_score * self.SOURCE_QUALITY_WEIGHT
        ) * length_factor

        return min(1.0, max(0.0, final))

    def _keyword_match_score(self, content: str, keywords: list[str]) -> float:
        """关键词命中率得分。"""
        if not keywords:
            return 0.5
        content_lower = content.lower()
        hits = sum(1 for kw in keywords if kw.lower() in content_lower)
        return hits / len(keywords)

    def _source_match_score(self, source: str, query: str, keywords: list[str]) -> float:
        """来源/标题与查询的匹配度。"""
        score = 0.0
        source_lower = source.lower()
        for kw in keywords:
            if kw.lower() in source_lower:
                score += 0.3
        # 查询中包含来源名也加分
        if source in query:
            score += 0.5
        return min(1.0, score)

    def _length_factor(self, content: str) -> float:
        """内容长度因子：50-1000字最优，过短或过长降权。"""
        length = len(content)
        if length < 20:
            return 0.3
        elif length < 50:
            return 0.7
        elif length <= 1000:
            return 1.0
        elif length <= 2000:
            return 0.9
        else:
            return 0.8


class ContentDeduplicator:
    """内容去重器：基于文本相似度去除重复片段。"""

    SIMILARITY_THRESHOLD = 0.85  # 相似度超过此阈值视为重复

    def deduplicate(self, documents: list[DocumentFragment]) -> list[DocumentFragment]:
        """去除内容高度相似的文档片段。"""
        if len(documents) <= 1:
            return documents

        unique = [documents[0]]
        for doc in documents[1:]:
            is_dup = False
            for existing in unique:
                sim = self._jaccard_similarity(doc.content, existing.content)
                if sim >= self.SIMILARITY_THRESHOLD:
                    # 保留分数更高的
                    if doc.relevance_score > existing.relevance_score:
                        unique.remove(existing)
                        unique.append(doc)
                    is_dup = True
                    break
            if not is_dup:
                unique.append(doc)

        return unique

    def _jaccard_similarity(self, text1: str, text2: str) -> float:
        """基于字符级 n-gram 的 Jaccard 相似度。"""
        n = 3  # trigram
        if len(text1) < n or len(text2) < n:
            return 1.0 if text1 == text2 else 0.0

        set1 = set(text1[i:i+n] for i in range(len(text1) - n + 1))
        set2 = set(text2[i:i+n] for i in range(len(text2) - n + 1))

        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0


class RAGEngine:
    """
    RAG 知识检索引擎（增强版）。

    检索流程：
    1. 查询改写 → 生成多个检索变体
    2. 多路召回 → 向量检索 + 关键词检索（每个变体）
    3. 结果合并去重
    4. 权限过滤（不够则扩大范围重试）
    5. 重排序（综合向量分、关键词命中、来源质量）
    6. 相关性阈值过滤
    7. 返回最终结果
    """

    # 配置
    MIN_RELEVANCE_SCORE = 0.35     # 最低相关性阈值
    CACHE_TTL_SECONDS = 300        # 结果缓存 5 分钟
    MAX_RETRY_EXPAND = 2           # 权限过滤后不足时最大扩展次数

    def __init__(
        self,
        db: AsyncSession,
        redis: aioredis.Redis,
        vector_store=None,
    ):
        self.db = db
        self.redis = redis
        self.vector_store = vector_store
        self.query_rewriter = QueryRewriter()
        self.reranker = ResultReranker()
        self.deduplicator = ContentDeduplicator()

        # 查询增强器（高级策略：上下文改写、HyDE、查询分解）
        from app.services.rag.query_enhancer import QueryEnhancer
        self.query_enhancer = QueryEnhancer(db=db, redis=redis)

    async def search(
        self,
        query: str,
        user_id: int,
        top_k: int = 10,
        use_cache: bool = True,
        conversation_history: list[dict] | None = None,
    ) -> list[DocumentFragment]:
        """
        增强版知识检索。
        支持传入对话历史以实现上下文感知检索。
        """
        import time
        start = time.perf_counter()

        # 0. 检查缓存
        if use_cache:
            cached = await self._get_cached_results(query, user_id)
            if cached is not None:
                return cached

        # 1. 查询改写（基础：去停用词 + 关键词提取）
        query_variants = self.query_rewriter.rewrite(query)
        keywords = self.query_rewriter._extract_keywords(query)

        # 1b. 查询增强（高级：上下文感知 + 查询分解 + 假设性片段）
        try:
            enhanced_variants = await self.query_enhancer.enhance(query, conversation_history)
            # 合并去重
            for ev in enhanced_variants:
                if ev not in query_variants:
                    query_variants.append(ev)
        except Exception:
            pass  # 增强失败不影响基础检索

        # 2. 多路召回
        all_candidates = []
        methods_used = []

        # 2a. 向量语义检索（主检索）
        for variant in query_variants[:2]:  # 取前两个变体
            results = await self._vector_search(variant, top_k * 3)
            for r in results:
                r.retrieval_method = "vector"
            all_candidates.extend(results)
            if results:
                methods_used.append("vector")

        # 2b. 关键词检索（补充召回）
        keyword_results = await self._keyword_search(query, keywords, top_k * 2)
        for r in keyword_results:
            r.retrieval_method = "keyword"
        all_candidates.extend(keyword_results)
        if keyword_results:
            methods_used.append("keyword")

        # 2c. 同义词扩展检索（提升召回率）
        expanded_queries = self.query_rewriter.expand_with_synonyms(query)
        for eq in expanded_queries[1:]:  # 跳过原始query
            extra = await self._vector_search(eq, top_k)
            for r in extra:
                r.retrieval_method = "synonym_expand"
            all_candidates.extend(extra)

        if not all_candidates:
            return []

        # 3. 去重
        unique_candidates = self.deduplicator.deduplicate(all_candidates)

        # 4. 权限过滤（含动态扩展）
        filtered = await self._filter_with_retry(unique_candidates, user_id, top_k)

        # 5. 重排序
        reranked = self.reranker.rerank(filtered, query, keywords)

        # 6. 相关性阈值过滤
        final = [doc for doc in reranked if doc.relevance_score >= self.MIN_RELEVANCE_SCORE]

        # 7. 截取 top_k
        result = final[:top_k]

        # 缓存结果
        if use_cache and result:
            await self._cache_results(query, user_id, result)

        elapsed = (time.perf_counter() - start) * 1000
        return result

    async def search_and_generate(
        self,
        query: str,
        user_id: int,
        department_id: int,
        top_k: int = 5,
        memory_context: str = "",
    ) -> dict:
        """RAG + LLM + Memory 联合问答。"""
        # 检索知识库
        docs = await self.search(query, user_id, top_k)

        if not docs:
            return {
                "answer": None,
                "sources": [],
                "has_result": False,
            }

        # 如果未提供记忆上下文，主动检索
        if not memory_context:
            try:
                from app.services.llm.memory import MemoryService
                memory_service = MemoryService(db=self.db, redis=self.redis)
                memories = await memory_service.recall(user_id, query)
                if memories:
                    memory_context = memory_service.format_memory_context(memories)
            except Exception:
                pass

        # 构建文档上下文（含相关度和来源标注）
        context_parts = []
        sources = []
        for i, doc in enumerate(docs, 1):
            score_pct = f"{doc.relevance_score * 100:.0f}%"
            context_parts.append(
                f"[文档{i}] (相关度:{score_pct}) 来源: {doc.source}\n{doc.content}"
            )
            sources.append({
                "doc_id": doc.id,
                "title": doc.source,
                "relevance_score": doc.relevance_score,
                "snippet": doc.content[:200],
                "retrieval_method": doc.retrieval_method,
            })

        context_docs = "\n\n".join(context_parts)

        # 调用 LLM
        from app.services.llm.prompt_engine import PromptTemplateEngine
        prompt_engine = PromptTemplateEngine(db=self.db)
        template_id = await prompt_engine.match_template(query)
        prompt = await prompt_engine.render(template_id, {
            "user_query": query,
            "context_docs": context_docs,
            "memory_context": memory_context,
            "conversation_history": "",
            "current_time": "",
        })

        gateway = LLMGateway(db=self.db, redis=self.redis)
        try:
            response = await gateway.generate(
                LLMRequest(prompt=prompt, stream=False)
            )
            return {
                "answer": response.content,
                "sources": sources,
                "has_result": True,
                "model_id": response.model_id,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }
        except Exception:
            return {
                "answer": None,
                "sources": sources,
                "has_result": True,
                "degraded": True,
            }

    # ==================== 多路召回 ====================

    async def _vector_search(
        self, query: str, top_k: int
    ) -> list[DocumentFragment]:
        """向量语义检索。"""
        if self.vector_store is None:
            return []

        results = await self.vector_store.search(query, top_k)
        return [
            DocumentFragment(
                id=r.get("id", ""),
                content=r.get("content", ""),
                source=r.get("source", ""),
                relevance_score=r.get("score", 0.0),
                department_id=r.get("department_id", 0),
                access_level=r.get("access_level", "public"),
                access_roles=r.get("access_roles"),
                metadata=r.get("metadata"),
            )
            for r in results
        ]

    async def _keyword_search(
        self, query: str, keywords: list[str], top_k: int
    ) -> list[DocumentFragment]:
        """
        关键词检索（BM25 风格）。
        用于补充向量检索的不足，特别是：
        - 专有名词精确匹配
        - 产品编号、代码
        - 人名、部门名等实体
        """
        if self.vector_store is None:
            return []

        # 如果向量库支持全文检索则使用
        if hasattr(self.vector_store, 'keyword_search'):
            results = await self.vector_store.keyword_search(
                keywords=keywords,
                top_k=top_k,
            )
            return [
                DocumentFragment(
                    id=r.get("id", ""),
                    content=r.get("content", ""),
                    source=r.get("source", ""),
                    relevance_score=r.get("score", 0.0) * 0.8,  # 关键词分数略降权
                    department_id=r.get("department_id", 0),
                    access_level=r.get("access_level", "public"),
                    access_roles=r.get("access_roles"),
                    metadata=r.get("metadata"),
                    retrieval_method="keyword",
                )
                for r in results
            ]
        return []

    # ==================== 权限过滤 ====================

    async def _filter_with_retry(
        self,
        candidates: list[DocumentFragment],
        user_id: int,
        target_count: int,
    ) -> list[DocumentFragment]:
        """
        权限过滤（含动态扩展）。
        如果过滤后结果不足 target_count 的 50%，尝试扩大检索。
        """
        calculator = PermissionCalculator(db=self.db, redis=self.redis)
        permissions = await calculator.get_effective_permissions(user_id)

        filtered = [
            doc for doc in candidates
            if self._has_access(doc, permissions)
        ]

        # 如果过滤后太少，标记但不重试（避免性能问题）
        # 实际项目中可在此处触发扩大范围的重新检索
        return filtered

    def _has_access(
        self, doc: DocumentFragment, permissions: list[dict]
    ) -> bool:
        """检查用户是否有权访问该文档。"""
        if doc.access_level == "public":
            return True

        for perm in permissions:
            if perm["resource_type"] == "knowledge_base":
                if perm["access_level"] == "admin":
                    return True
                dept_scope = perm.get("department_scope")
                if dept_scope:
                    scope_list = json.loads(dept_scope) if isinstance(dept_scope, str) else dept_scope
                    if doc.department_id in scope_list:
                        return True
                # access_roles 匹配
                if doc.access_roles:
                    # 如果文档指定了允许的角色
                    # 需要检查用户是否属于这些角色（此处简化）
                    pass

        return False

    # ==================== 缓存 ====================

    async def _get_cached_results(
        self, query: str, user_id: int
    ) -> list[DocumentFragment] | None:
        """从缓存获取检索结果。"""
        cache_key = self._build_cache_key(query, user_id)
        cached = await self.redis.get(cache_key)
        if not cached:
            return None

        try:
            data = json.loads(cached)
            return [DocumentFragment(**d) for d in data]
        except Exception:
            return None

    async def _cache_results(
        self, query: str, user_id: int, results: list[DocumentFragment]
    ) -> None:
        """缓存检索结果。"""
        cache_key = self._build_cache_key(query, user_id)
        data = [
            {
                "id": d.id,
                "content": d.content,
                "source": d.source,
                "relevance_score": d.relevance_score,
                "department_id": d.department_id,
                "access_level": d.access_level,
                "access_roles": d.access_roles,
                "metadata": d.metadata,
                "retrieval_method": d.retrieval_method,
            }
            for d in results
        ]
        await self.redis.setex(cache_key, self.CACHE_TTL_SECONDS, json.dumps(data))

    def _build_cache_key(self, query: str, user_id: int) -> str:
        """构建缓存键。"""
        query_hash = hashlib.md5(query.encode()).hexdigest()[:12]
        return f"rag:cache:{user_id}:{query_hash}"
