"""Token 监控服务：用量记录、配额管理、成本估算。"""

from datetime import datetime, timezone
from decimal import Decimal

import redis.asyncio as aioredis
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import LLM_003, QuotaExceededException
from app.models.llm import TokenQuota, TokenUsageRecord


class TokenMonitorService:
    """
    Token 监控服务。
    - 记录每次 LLM 调用的 Token 用量和费用
    - 管理配额（用户/部门级别）
    - 成本估算和预警
    """

    # 各模型定价（每千 Token，单位：元）
    MODEL_PRICING: dict[str, dict[str, float]] = {
        "openai:gpt-4": {"input": 0.21, "output": 0.42},
        "openai:gpt-4o": {"input": 0.0175, "output": 0.07},
        "openai:gpt-3.5-turbo": {"input": 0.01, "output": 0.02},
        "qwen:qwen-plus": {"input": 0.008, "output": 0.02},
        "qwen:qwen-turbo": {"input": 0.002, "output": 0.006},
        "wenxin:ernie-4.0": {"input": 0.12, "output": 0.12},
        "wenxin:ernie-3.5": {"input": 0.008, "output": 0.008},
    }

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def record_usage(
        self,
        user_id: int,
        department_id: int,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        conversation_id: int | None = None,
        request_type: str = "chat",
    ) -> None:
        """记录一次 LLM 调用的 Token 用量和费用。"""
        cost = self._estimate_cost(model_id, input_tokens, output_tokens)

        record = TokenUsageRecord(
            user_id=user_id,
            department_id=department_id,
            conversation_id=conversation_id,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=Decimal(str(cost)),
            request_type=request_type,
        )
        self.db.add(record)
        await self.db.flush()

        # 更新配额计数
        await self._update_quota_counter(user_id, department_id, input_tokens + output_tokens, cost)

    async def check_quota(self, user_id: int, department_id: int | None = None) -> None:
        """
        检查 Token 配额。
        - 达到 80% 触发预警（记录日志）
        - 达到 100% 抛出异常阻止调用
        """
        # 检查用户级配额
        user_quota = await self._get_quota("user", user_id)
        if user_quota and user_quota.is_active:
            if user_quota.current_month_tokens >= user_quota.monthly_token_limit:
                raise QuotaExceededException(target_type="user", target_id=user_id)
            await self._check_alert_threshold(user_quota)

        # 检查部门级配额
        if department_id:
            dept_quota = await self._get_quota("department", department_id)
            if dept_quota and dept_quota.is_active:
                if dept_quota.current_month_tokens >= dept_quota.monthly_token_limit:
                    raise QuotaExceededException(target_type="department", target_id=department_id)
                await self._check_alert_threshold(dept_quota)

    async def get_usage_summary(
        self,
        user_id: int | None = None,
        department_id: int | None = None,
        model_id: str | None = None,
    ) -> dict:
        """获取 Token 用量统计摘要。"""
        conditions = []
        if user_id:
            conditions.append(TokenUsageRecord.user_id == user_id)
        if department_id:
            conditions.append(TokenUsageRecord.department_id == department_id)
        if model_id:
            conditions.append(TokenUsageRecord.model_id == model_id)

        stmt = select(
            func.sum(TokenUsageRecord.input_tokens).label("total_input"),
            func.sum(TokenUsageRecord.output_tokens).label("total_output"),
            func.sum(TokenUsageRecord.estimated_cost).label("total_cost"),
            func.count(TokenUsageRecord.id).label("total_calls"),
        ).where(*conditions)

        result = await self.db.execute(stmt)
        row = result.one()

        return {
            "total_input_tokens": row.total_input or 0,
            "total_output_tokens": row.total_output or 0,
            "total_cost": float(row.total_cost or 0),
            "total_calls": row.total_calls or 0,
        }

    async def set_quota(
        self,
        target_type: str,
        target_id: int,
        monthly_token_limit: int,
        monthly_cost_limit: float | None = None,
        alert_threshold: float = 0.8,
    ) -> TokenQuota:
        """设置或更新 Token 配额。"""
        stmt = select(TokenQuota).where(
            TokenQuota.target_type == target_type,
            TokenQuota.target_id == target_id,
        )
        result = await self.db.execute(stmt)
        quota = result.scalar_one_or_none()

        if quota:
            quota.monthly_token_limit = monthly_token_limit
            quota.monthly_cost_limit = Decimal(str(monthly_cost_limit)) if monthly_cost_limit else None
            quota.alert_threshold = alert_threshold
        else:
            quota = TokenQuota(
                target_type=target_type,
                target_id=target_id,
                monthly_token_limit=monthly_token_limit,
                monthly_cost_limit=Decimal(str(monthly_cost_limit)) if monthly_cost_limit else None,
                alert_threshold=alert_threshold,
            )
            self.db.add(quota)

        await self.db.flush()
        return quota

    def _estimate_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        """估算单次调用费用。"""
        pricing = self._get_pricing(model_id)
        return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000

    def _get_pricing(self, model_id: str) -> dict[str, float]:
        """获取模型定价。"""
        # 精确匹配
        if model_id in self.MODEL_PRICING:
            return self.MODEL_PRICING[model_id]

        # 前缀匹配
        for key, pricing in self.MODEL_PRICING.items():
            if model_id.startswith(key.split(":")[0]):
                return pricing

        # 本地模型无费用
        return {"input": 0.0, "output": 0.0}

    async def _get_quota(self, target_type: str, target_id: int) -> TokenQuota | None:
        """获取配额信息。"""
        stmt = select(TokenQuota).where(
            TokenQuota.target_type == target_type,
            TokenQuota.target_id == target_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _update_quota_counter(
        self, user_id: int, department_id: int, tokens: int, cost: float
    ) -> None:
        """更新配额计数器。"""
        # 更新用户级
        await self.db.execute(
            update(TokenQuota)
            .where(TokenQuota.target_type == "user", TokenQuota.target_id == user_id)
            .values(
                current_month_tokens=TokenQuota.current_month_tokens + tokens,
                current_month_cost=TokenQuota.current_month_cost + Decimal(str(cost)),
            )
        )
        # 更新部门级
        await self.db.execute(
            update(TokenQuota)
            .where(TokenQuota.target_type == "department", TokenQuota.target_id == department_id)
            .values(
                current_month_tokens=TokenQuota.current_month_tokens + tokens,
                current_month_cost=TokenQuota.current_month_cost + Decimal(str(cost)),
            )
        )

    async def _check_alert_threshold(self, quota: TokenQuota) -> None:
        """检查预警阈值。"""
        if not quota or not quota.is_active:
            return
        ratio = quota.current_month_tokens / quota.monthly_token_limit
        if ratio >= quota.alert_threshold:
            # 记录预警（避免重复，使用 Redis）
            alert_key = f"token_alert:{quota.target_type}:{quota.target_id}"
            already = await self.redis.get(alert_key)
            if not already:
                await self.redis.setex(alert_key, 86400, "1")  # 24h 内不重复预警
                # 实际项目中此处发送通知
