"""Token cost monitoring service."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.llm import TokenUsageRecord

logger = logging.getLogger(__name__)


class CostMonitorService:
    """Aggregate token costs and detect abnormal usage."""

    ANOMALY_MULTIPLIER = 3.0
    ALERT_COOLDOWN_HOURS = 4

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def get_cost_dashboard(self, user_id: int | None = None, days: int = 30) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        conditions = [TokenUsageRecord.created_at >= since]
        if user_id is not None:
            conditions.append(TokenUsageRecord.user_id == user_id)

        total_row = (
            await self.db.execute(
                select(
                    func.sum(TokenUsageRecord.input_tokens).label("input"),
                    func.sum(TokenUsageRecord.output_tokens).label("output"),
                    func.sum(TokenUsageRecord.estimated_cost).label("cost"),
                    func.count(TokenUsageRecord.id).label("calls"),
                ).where(*conditions)
            )
        ).one()

        model_rows = (
            await self.db.execute(
                select(
                    TokenUsageRecord.model_id,
                    func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens).label("tokens"),
                    func.sum(TokenUsageRecord.estimated_cost).label("cost"),
                    func.count(TokenUsageRecord.id).label("calls"),
                )
                .where(*conditions)
                .group_by(TokenUsageRecord.model_id)
            )
        ).all()

        user_rows = (
            await self.db.execute(
                select(
                    TokenUsageRecord.user_id,
                    func.sum(TokenUsageRecord.estimated_cost).label("cost"),
                    func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens).label("tokens"),
                )
                .where(*conditions)
                .group_by(TokenUsageRecord.user_id)
                .order_by(func.sum(TokenUsageRecord.estimated_cost).desc())
                .limit(10)
            )
        ).all()

        total_cost = float(total_row.cost or 0)
        total_calls = total_row.calls or 0
        return {
            "period_days": days,
            "total_cost": total_cost,
            "total_tokens": (total_row.input or 0) + (total_row.output or 0),
            "total_calls": total_calls,
            "avg_cost_per_call": round(total_cost / max(total_calls, 1), 4),
            "model_breakdown": [
                {"model_id": row.model_id, "tokens": row.tokens or 0, "cost": float(row.cost or 0), "calls": row.calls or 0}
                for row in model_rows
            ],
            "top_users": [
                {"user_id": row.user_id, "cost": float(row.cost or 0), "tokens": row.tokens or 0}
                for row in user_rows
            ],
        }

    async def check_anomaly(self, user_id: int, current_hour_tokens: int) -> bool:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        total_7d = (
            await self.db.execute(
                select(func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens)).where(
                    TokenUsageRecord.user_id == user_id,
                    TokenUsageRecord.created_at >= since,
                )
            )
        ).scalar() or 0
        avg_hourly = total_7d / (7 * 24) if total_7d > 0 else 100
        if current_hour_tokens <= avg_hourly * self.ANOMALY_MULTIPLIER:
            return False

        alert_key = f"cost_alert:{user_id}"
        if await self.redis.get(alert_key):
            return False

        await self.redis.setex(alert_key, self.ALERT_COOLDOWN_HOURS * 3600, "1")
        logger.warning(
            "[CostMonitor] Abnormal usage user=%s current_hour=%s avg_hourly=%.0f multiplier=%.1fx",
            user_id,
            current_hour_tokens,
            avg_hourly,
            current_hour_tokens / max(avg_hourly, 1),
        )
        return True

    async def should_degrade(self) -> bool:
        threshold = settings.LLM_RATE_LIMIT_PER_HOUR * 50
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        total = (
            await self.db.execute(
                select(func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens)).where(
                    TokenUsageRecord.created_at >= since
                )
            )
        ).scalar() or 0
        return total > threshold

    async def get_user_current_hour_usage(self, user_id: int) -> int:
        hour_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        return (
            await self.db.execute(
                select(func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens)).where(
                    TokenUsageRecord.user_id == user_id,
                    TokenUsageRecord.created_at >= hour_start,
                )
            )
        ).scalar() or 0
