"""Token 监控 API 路由。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.redis import get_redis
from app.models.llm import TokenQuota
from app.schemas.llm import SetQuotaRequest, TokenDashboardResponse, TokenUsageSummary
from app.services.auth.dependencies import get_current_user
from app.services.llm.token_monitor import TokenMonitorService
from app.services.permission.middleware import require_admin

router = APIRouter()


@router.get("/usage", response_model=TokenUsageSummary)
async def get_usage(
    user_id: int | None = Query(default=None),
    department_id: int | None = Query(default=None),
    model_id: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """获取 Token 用量统计。"""
    monitor = TokenMonitorService(db=db, redis=redis)
    summary = await monitor.get_usage_summary(
        user_id=user_id or current_user["user_id"],
        department_id=department_id,
        model_id=model_id,
    )
    return TokenUsageSummary(**summary)


@router.get("/dashboard", response_model=TokenDashboardResponse)
async def get_dashboard(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """实时仪表盘数据。"""
    monitor = TokenMonitorService(db=db, redis=redis)
    summary = await monitor.get_usage_summary()

    # 获取配额列表
    stmt = select(TokenQuota).where(TokenQuota.is_active == True)
    result = await db.execute(stmt)
    quotas = result.scalars().all()

    return TokenDashboardResponse(
        current_month=TokenUsageSummary(**summary),
        quotas=[
            {
                "target_type": q.target_type,
                "target_id": q.target_id,
                "monthly_limit": q.monthly_token_limit,
                "current_usage": q.current_month_tokens,
                "usage_ratio": q.current_month_tokens / q.monthly_token_limit if q.monthly_token_limit else 0,
            }
            for q in quotas
        ],
    )


@router.post("/quotas", status_code=201)
async def set_quota(
    request: SetQuotaRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    _admin=Depends(require_admin),
):
    """设置 Token 配额（管理员）。"""
    monitor = TokenMonitorService(db=db, redis=redis)
    quota = await monitor.set_quota(
        target_type=request.target_type,
        target_id=request.target_id,
        monthly_token_limit=request.monthly_token_limit,
        monthly_cost_limit=request.monthly_cost_limit,
        alert_threshold=request.alert_threshold,
    )
    return {"id": quota.id, "message": "配额设置成功"}
