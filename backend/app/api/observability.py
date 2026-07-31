"""可观测性 API：Agent 执行轨迹查询、统计。"""

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
    """获取当前用户的 Agent 执行轨迹列表。"""
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
    """获取单条轨迹详情（校验用户归属）。"""
    service = TraceQueryService(db)
    result = await service.get_trace(trace_id)
    if not result:
        raise HTTPException(status_code=404, detail="轨迹不存在")

    # 归属校验：只能查看自己的轨迹（管理员除外）
    trace_user_id = result["trace"].get("user_id")
    is_admin = "admin" in current_user.get("roles", [])
    if trace_user_id != current_user["user_id"] and not is_admin:
        raise HTTPException(status_code=403, detail="无权查看该轨迹")

    return result


@router.get("/stats")
async def get_observability_stats(
    days: int = Query(default=7, ge=1, le=90),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取可观测性统计摘要（仅当前用户数据）。"""
    service = TraceQueryService(db)
    stats = await service.get_stats(
        user_id=current_user["user_id"],
        days=days,
    )
    return stats
