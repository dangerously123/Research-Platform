"""知识检索 API 路由（增强版）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.redis import get_redis
from app.services.auth.dependencies import get_current_user
from app.services.permission.middleware import require_admin
from app.services.rag.engine import RAGEngine
from app.services.rag.vector_store import get_knowledge_store

router = APIRouter()


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    use_llm: bool = True
    use_cache: bool = True


class DocumentUploadRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=10)
    department_id: int
    access_level: str = Field(default="public", description="public/internal/confidential")
    access_roles: list[int] | None = None
    doc_type: str = Field(default="general")


class DocumentFragmentResponse(BaseModel):
    id: str
    content: str
    source: str
    relevance_score: float
    retrieval_method: str = "vector"


class KnowledgeSearchResponse(BaseModel):
    query: str
    answer: str | None = None
    sources: list[dict] = []
    has_result: bool
    degraded: bool = False


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    知识库语义检索（增强版）。
    使用混合检索策略：向量语义 + 关键词 + 查询改写 + 重排序。
    """
    store = get_knowledge_store()
    engine = RAGEngine(db=db, redis=redis, vector_store=store)
    user_id = current_user["user_id"]
    department_id = current_user.get("department_id", 0)

    if request.use_llm:
        result = await engine.search_and_generate(
            query=request.query,
            user_id=user_id,
            department_id=department_id,
            top_k=request.top_k,
        )
        return KnowledgeSearchResponse(
            query=request.query,
            answer=result.get("answer"),
            sources=result.get("sources", []),
            has_result=result.get("has_result", False),
            degraded=result.get("degraded", False),
        )
    else:
        docs = await engine.search(
            query=request.query,
            user_id=user_id,
            top_k=request.top_k,
            use_cache=request.use_cache,
        )
        return KnowledgeSearchResponse(
            query=request.query,
            sources=[
                {
                    "doc_id": d.id,
                    "title": d.source,
                    "relevance_score": d.relevance_score,
                    "snippet": d.content[:200],
                    "retrieval_method": d.retrieval_method,
                }
                for d in docs
            ],
            has_result=len(docs) > 0,
        )


@router.post("/documents", status_code=201)
async def upload_document(
    request: DocumentUploadRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    _admin=Depends(require_admin),
):
    """
    上传文档到知识库（管理员）。
    自动切分、生成嵌入、建立向量索引和关键词索引。
    """
    from uuid import uuid4

    store = get_knowledge_store()
    doc_id = f"doc_{uuid4().hex[:12]}"

    chunks_count = await store.add_documents(
        doc_id=doc_id,
        title=request.title,
        content=request.content,
        department_id=request.department_id,
        access_level=request.access_level,
        access_roles=request.access_roles,
        doc_type=request.doc_type,
    )
    await redis.incr("rag:knowledge:version")

    return {
        "doc_id": doc_id,
        "title": request.title,
        "chunks_created": chunks_count,
        "message": f"文档已成功入库，切分为 {chunks_count} 个片段",
    }


@router.delete("/documents/{doc_id}", status_code=200)
async def delete_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
    _admin=Depends(require_admin),
):
    """删除知识库文档（管理员）。"""
    store = get_knowledge_store()
    deleted_count = await store.delete_document(doc_id)
    if deleted_count:
        await redis.incr("rag:knowledge:version")
    return {
        "doc_id": doc_id,
        "chunks_deleted": deleted_count,
        "message": f"已删除 {deleted_count} 个片段",
    }


@router.get("/stats")
async def get_knowledge_stats(
    current_user: dict = Depends(get_current_user),
):
    """获取知识库统计信息。"""
    store = get_knowledge_store()
    stats = await store.get_stats()
    return stats
