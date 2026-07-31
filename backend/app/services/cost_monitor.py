"""
成本监控服务：Token 成本追踪、异常消费告警、预算控制。

职责：
- 实时追踪各用户/部门的 Token 消耗和费用
- 异常消费检测（突增告警）
- 预算超限自动降级
- 成本面板数据聚合
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import redis.asyncio as aioredis
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.llm import TokenUsageRecord, TokenQuota

logger = logging.getLogger(__name__)


class CostMonitorService:
    """成本监控服务。"""

    # 异常消费检测：当前小时消耗超过过去7天平均的 N 倍
    ANOMALY_MULTIPLIER = 3.0
    # 告警冷却时间（同一目标 N 小时内不重复告警）
    ALERT_COOLDOWN_HOURS = 4

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def get_cost_dashboard(
        self, user_id: int | None = None, days: int = 30
    ) -> dict:
        """
        获取成本面板数据。

        Returns:
            {
                "period_days": 30,
                "total_cost": 12.5,
                "total_tokens": 500000,
                "daily_breakdown": [...],
                "model_breakdown": [...],
                "top_users": [...],
            }
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        conditions = [TokenUsageRecord.created_at >= since]
        if user_id:
            conditions.append(TokenUsageRecord.user_id == user_id)

        # 总量统计
        total_stmt = select(
            func.sum(TokenUsageRecord.input_tokens).label("input"),
            func.sum(TokenUsageRecord.output_tokens).label("output"),
            func.sum(TokenUsageRecord.estimated_cost).label("cost"),
            func.count(TokenUsageRecord.id).label("calls"),
        ).where(*conditions)
        total_row = (await self.db.execute(total_stmt)).one()

        # 按模型分组
        model_stmt = select(
            TokenUsageRecord.model_id,
            func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens).label("tokens"),
            func.sum(TokenUsageRecord.estimated_cost).label("cost"),
            func.count(TokenUsageRecord.id).label("calls"),
        ).where(*conditions).group_by(TokenUsageRecord.model_id)
        model_rows = (await self.db.execute(model_stmt)).all()

        # 按用户 TOP 10
        user_stmt = select(
            TokenUsageRecord.user_id,
            func.sum(TokenUsageRecord.estimated_cost).label("cost"),
            func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens).label("tokens"),
        ).where(*conditions).group_by(
            TokenUsageRecord.user_id
        ).order_by(func.sum(TokenUsageRecord.estimated_cost).desc()).limit(10)
        user_rows = (await self.db.execute(user_stmt)).all()

        return {
            "period_days": days,
            "total_cost": float(total_row.cost or 0),
            "total_tokens": (total_row.input or 0) + (total_row.output or 0),
            "total_calls": total_row.calls or 0,
            "avg_cost_per_call": round(
                float(total_row.cost or 0) / max(total_row.calls or 1, 1), 4
            ),
            "model_breakdown": [
                {"model_id": r.model_id, "tokens": r.tokens or 0,
                 "cost": float(r.cost or 0), "calls": r.calls}
                for r in model_rows
            ],
            "top_users": [
                {"user_id": r.user_id, "cost": float(r.cost or 0), "tokens": r.tokens or 0}
                for r in user_rows
            ],
        }

    async def check_anomaly(self, user_id: int, current_hour_tokens: int) -> bool:
        """
        检测异常消费。
        如果当前小时消耗超过近 7 天每小时平均的 N 倍，触发告警。

        Returns:
            True 如果检测到异常
        """
        # 计算近7天每小时平均 token
        since = datetime.now(timezone.utc) - timedelta(days=7)
        stmt = select(
            func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens)
        ).where(
            TokenUsageRecord.user_id == user_id,
            TokenUsageRecord.created_at >= since,
        )
        total_7d = (await self.db.execute(stmt)).scalar() or 0
        avg_hourly = total_7d / (7 * 24) if total_7d > 0 else 100

        is_anomaly = current_hour_tokens > avg_hourly * self.ANOMALY_MULTIPLIER

        if is_anomaly:
            # 冷却检查
            alert_key = f"cost_alert:{user_id}"
            already_alerted = await self.redis.get(alert_key)
            if not already_alerted:
                await self.redis.setex(
                    alert_key, self.ALERT_COOLDOWN_HOURS * 3600, "1"
                )
                logger.warning(
                    f"[CostMonitor] 异常消费检测: user={user_id} "
                    f"current_hour={current_hour_tokens} "
                    f"avg_hourly={avg_hourly:.0f} "
                    f"multiplier={current_hour_tokens/max(avg_hourly,1):.1f}x"
                )
                return True

        return False

    async def should_degrade(self) -> bool:
        """
        判断是否应该触发全局降级。
        条件：过去1小时总 token 消耗超过阈值。
        """
        threshold = settings.LLM_RATE_LIMIT_PER_HOUR * 50  # 总调用数 × 平均token
        since = datetime.now(timezone.utc) - timedelta(hours=1)

        stmt = select(
            func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens)
        ).where(TokenUsageRecord.created_at >= since)
        total = (await self.db.execute(stmt)).scalar() or 0

        return total > threshold

    async def get_user_current_hour_usage(self, user_id: int) -> int:
        """获取用户当前小时的 token 用量。"""
        hour_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        stmt = select(
            func.sum(TokenUsageRecord.input_tokens + TokenUsageRecord.output_tokens)
        ).where(
            TokenUsageRecord.user_id == user_id,
            TokenUsageRecord.created_at >= hour_start,
        )
        return (await self.db.execute(stmt)).scalar() or 0
