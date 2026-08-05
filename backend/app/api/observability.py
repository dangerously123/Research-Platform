"""Observability API for Agent traces and stats."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.auth.dependencies import get_current_user
from app.services.observability import TraceQueryService

router = APIRouter()


@router.get("/traces")
async def list_traces(
    conversation_id: int | None = Query(default=None),
    execution_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List Agent traces for the current user."""
    service = TraceQueryService(db)
    traces, total = await service.list_traces(
        user_id=current_user["user_id"],
        conversation_id=conversation_id,
        execution_type=execution_type,
        page=page,
        page_size=page_size,
    )
    return {"traces": traces, "total": total, "page": page}


@router.get("/traces/{trace_id}")
async def get_trace_detail(
    trace_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get one trace detail for the trace owner only."""
    service = TraceQueryService(db)
    result = await service.get_trace(trace_id)
    if not result:
        raise HTTPException(status_code=404, detail="Trace not found")

    trace_user_id = result["trace"].get("user_id")
    if trace_user_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Trace access denied")

    return result


@router.get("/stats")
async def get_observability_stats(
    days: int = Query(default=7, ge=1, le=90),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get observability stats for the current user."""
    service = TraceQueryService(db)
    return await service.get_stats(user_id=current_user["user_id"], days=days)
