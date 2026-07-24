"""异常检测模块：基于 Redis 滑动窗口检测异常数据访问模式。"""

from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SecurityAlert


class AnomalyDetector:
    """
    数据访问异常检测器。
    基于 Redis 计数器的滑动窗口机制检测异常行为。
    """

    # 阈值配置
    EXPORT_THRESHOLD = 10       # 1小时内导出次数上限
    QUERY_THRESHOLD = 200       # 1小时内查询次数上限
    LLM_CALL_THRESHOLD = 100    # 1小时内 LLM 调用次数上限
    WINDOW_SECONDS = 3600       # 检测窗口（1小时）

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def check_access_pattern(self, user_id: int, operation: str) -> bool:
        """
        检查用户访问模式是否异常。

        Args:
            user_id: 用户 ID
            operation: 操作类型 (export/query/llm_call)

        Returns:
            True 表示异常（已触发告警），False 表示正常。
        """
        key = f"access_count:{user_id}:{operation}"
        count = await self.redis.incr(key)

        if count == 1:
            await self.redis.expire(key, self.WINDOW_SECONDS)

        threshold = self._get_threshold(operation)

        if count > threshold:
            await self._trigger_alert(user_id, operation, count)
            return True

        return False

    async def get_current_count(self, user_id: int, operation: str) -> int:
        """获取当前窗口内的操作次数。"""
        key = f"access_count:{user_id}:{operation}"
        count = await self.redis.get(key)
        return int(count) if count else 0

    def _get_threshold(self, operation: str) -> int:
        """获取操作对应的阈值。"""
        thresholds = {
            "export": self.EXPORT_THRESHOLD,
            "query": self.QUERY_THRESHOLD,
            "llm_call": self.LLM_CALL_THRESHOLD,
        }
        return thresholds.get(operation, self.QUERY_THRESHOLD)

    async def _trigger_alert(self, user_id: int, operation: str, count: int) -> None:
        """触发安全告警。"""
        # 避免重复告警：同一用户同一操作在窗口内只告警一次
        alert_key = f"alert_sent:{user_id}:{operation}"
        already_sent = await self.redis.get(alert_key)
        if already_sent:
            return

        # 创建安全告警记录
        alert = SecurityAlert(
            alert_type="abnormal_access",
            user_id=user_id,
            description=f"用户 {user_id} 在 1 小时内执行了 {count} 次 {operation} 操作，"
                        f"超过阈值 {self._get_threshold(operation)}",
            severity="high" if count > self._get_threshold(operation) * 2 else "medium",
            status="open",
        )
        self.db.add(alert)
        await self.db.flush()

        # 标记已告警，窗口内不再重复
        await self.redis.setex(alert_key, self.WINDOW_SECONDS, "1")
