"""User memory management API routes."""

from datetime import datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

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
    query: str = Field(..., min_length=1, max_length=1000)
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
    """List current user's memories."""
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
                id=record.id,
                question=record.question,
                answer_summary=record.answer_summary,
                key_facts=record.key_facts,
                topic_tags=record.topic_tags,
                importance=record.importance,
                access_count=record.access_count,
                created_at=record.created_at,
                last_accessed_at=record.last_accessed_at,
            )
            for record in records
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
    """Semantic-search current user's memories."""
    service = MemoryService(db=db, redis=redis)
    results = await service.recall(
        user_id=current_user["user_id"],
        query=request.query,
        top_k=request.top_k,
        min_score=0.5,
    )
    return MemorySearchResponse(
        query=request.query,
        results=[
            {
                "memory_id": item["memory_id"],
                "question": item["question"],
                "answer_summary": item["answer_summary"],
                "score": round(item["score"], 3),
                "topic_tags": item["topic_tags"],
                "created_at": item["created_at"].isoformat() if item.get("created_at") else None,
            }
            for item in results
        ],
    )


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Delete one memory owned by current user."""
    service = MemoryService(db=db, redis=redis)
    deleted = await service.delete_memory(user_id=current_user["user_id"], memory_id=memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")


@router.delete("", status_code=200)
async def clear_all_memories(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Delete all memories owned by current user."""
    service = MemoryService(db=db, redis=redis)
    count = await service.clear_all_memories(current_user["user_id"])
    return {"message": f"Deleted {count} memories", "deleted": count}
