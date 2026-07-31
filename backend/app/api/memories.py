"""用户记忆管理 API 路由：查看、搜索、删除个人记忆。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.redis import get_redis
from app.services.auth.dependencies import get_current_user
from app.services.llm.memory import MemoryService

router = APIRouter()


class MemoryResponse(BaseModel):
    id: int
    question: str
    answer_summary: str
    key_facts: list | None = None
    topic_tags: str | None = None
    importance: float
    access_count: int
    created_at: datetime
    last_accessed_at: datetime | None = None


class MemoryListResponse(BaseModel):
    memories: list[MemoryResponse]
    total: int
    page: int
    page_size: int


class MemorySearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class MemorySearchResponse(BaseModel):
    query: str
    results: list[dict]


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    topic: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """获取当前用户的记忆列表（分页）。"""
    service = MemoryService(db=db, redis=redis)
    records, total = await service.get_user_memories(
        user_id=current_user["user_id"],
        page=page,
        page_size=page_size,
        topic=topic,
    )

    return MemoryListResponse(
        memories=[
            MemoryResponse(
                id=r.id,
                question=r.question,
                answer_summary=r.answer_summary,
                key_facts=r.key_facts,
                topic_tags=r.topic_tags,
                importance=r.importance,
                access_count=r.access_count,
                created_at=r.created_at,
                last_accessed_at=r.last_accessed_at,
            )
            for r in records
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(
    request: MemorySearchRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """语义搜索个人记忆。"""
    service = MemoryService(db=db, redis=redis)
    results = await service.recall(
        user_id=current_user["user_id"],
        query=request.query,
        top_k=request.top_k,
        min_score=0.5,  # 搜索时放宽阈值
    )

    return MemorySearchResponse(
        query=request.query,
        results=[
            {
                "memory_id": m["memory_id"],
                "question": m["question"],
                "answer_summary": m["answer_summary"],
                "score": round(m["score"], 3),
                "topic_tags": m["topic_tags"],
                "created_at": m["created_at"].isoformat() if m.get("created_at") else None,
            }
            for m in results
        ],
    )


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """删除指定记忆。"""
    service = MemoryService(db=db, redis=redis)
    deleted = await service.delete_memory(
        user_id=current_user["user_id"],
        memory_id=memory_id,
    )
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="记忆不存在")


@router.delete("", status_code=200)
async def clear_all_memories(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """清空当前用户的所有记忆。"""
    service = MemoryService(db=db, redis=redis)
    count = await service.clear_all_memories(current_user["user_id"])
    return {"message": f"已清空 {count} 条记忆"}
