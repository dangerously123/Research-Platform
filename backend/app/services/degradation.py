"""
LLM 降级策略服务。

场景：
- 高峰期自动切换到更便宜/更快的模型
- 主模型故障时降级到备选模型
- 成本超限时降低推理深度
- 手动降级开关（运维控制）

降级级别：
- NORMAL: 正常模式，使用配置的优先级模型
- LIGHT: 轻度降级，减少 ReAct 轮数，降低 context 窗口
- HEAVY: 重度降级，只使用最便宜模型，禁用 ReAct
- FALLBACK: 兜底模式，纯检索回答，不调用 LLM
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class DegradationLevel(IntEnum):
    """降级级别。"""
    NORMAL = 0
    LIGHT = 1
    HEAVY = 2
    FALLBACK = 3


@dataclass
class DegradationConfig:
    """各降级级别的配置参数。"""
    level: DegradationLevel
    max_iterations: int          # ReAct 最大轮数
    max_output_tokens: int       # 最大输出 token
    allow_react: bool            # 是否允许 ReAct 循环
    allow_tools: bool            # 是否允许工具调用
    allow_memory: bool           # 是否允许长期记忆
    preferred_model_tier: str    # 优先模型层级: premium / standard / economy
    context_window_ratio: float  # 上下文窗口使用比例


# 各级别默认配置
DEGRADATION_CONFIGS: dict[DegradationLevel, DegradationConfig] = {
    DegradationLevel.NORMAL: DegradationConfig(
        level=DegradationLevel.NORMAL,
        max_iterations=5,
        max_output_tokens=4096,
        allow_react=True,
        allow_tools=True,
        allow_memory=True,
        preferred_model_tier="premium",
        context_window_ratio=1.0,
    ),
    DegradationLevel.LIGHT: DegradationConfig(
        level=DegradationLevel.LIGHT,
        max_iterations=3,
        max_output_tokens=2048,
        allow_react=True,
        allow_tools=True,
        allow_memory=True,
        preferred_model_tier="standard",
        context_window_ratio=0.7,
    ),
    DegradationLevel.HEAVY: DegradationConfig(
        level=DegradationLevel.HEAVY,
        max_iterations=1,
        max_output_tokens=1024,
        allow_react=False,
        allow_tools=False,
        allow_memory=False,
        preferred_model_tier="economy",
        context_window_ratio=0.5,
    ),
    DegradationLevel.FALLBACK: DegradationConfig(
        level=DegradationLevel.FALLBACK,
        max_iterations=0,
        max_output_tokens=512,
        allow_react=False,
        allow_tools=False,
        allow_memory=False,
        preferred_model_tier="economy",
        context_window_ratio=0.3,
    ),
}


class DegradationService:
    """
    降级策略服务。

    降级状态存储在 Redis 中，支持：
    - 自动降级（基于负载/成本触发）
    - 手动降级（运维人员通过 API 控制）
    - 自动恢复（降级条件消失后回到正常）
    """

    REDIS_KEY = "system:degradation_level"
    REDIS_MANUAL_KEY = "system:degradation_manual"

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    async def get_current_level(self) -> DegradationLevel:
        """获取当前降级级别。"""
        # 手动降级优先
        manual = await self.redis.get(self.REDIS_MANUAL_KEY)
        if manual:
            return DegradationLevel(int(manual))

        # 自动降级
        auto = await self.redis.get(self.REDIS_KEY)
        if auto:
            return DegradationLevel(int(auto))

        return DegradationLevel.NORMAL

    async def get_current_config(self) -> DegradationConfig:
        """获取当前降级配置。"""
        level = await self.get_current_level()
        return DEGRADATION_CONFIGS[level]

    async def set_auto_level(self, level: DegradationLevel, ttl_seconds: int = 600) -> None:
        """
        设置自动降级级别（带 TTL，自动恢复）。

        Args:
            level: 降级级别
            ttl_seconds: 自动恢复时间（默认10分钟）
        """
        if level == DegradationLevel.NORMAL:
            await self.redis.delete(self.REDIS_KEY)
        else:
            await self.redis.setex(self.REDIS_KEY, ttl_seconds, str(level.value))

        logger.warning(
            f"[Degradation] 自动降级: level={level.name} ttl={ttl_seconds}s"
        )

    async def set_manual_level(self, level: DegradationLevel) -> None:
        """
        设置手动降级级别（无 TTL，需手动恢复）。
        """
        if level == DegradationLevel.NORMAL:
            await self.redis.delete(self.REDIS_MANUAL_KEY)
            logger.info("[Degradation] 手动降级已解除")
        else:
            await self.redis.set(self.REDIS_MANUAL_KEY, str(level.value))
            logger.warning(f"[Degradation] 手动降级设置: level={level.name}")

    async def get_status(self) -> dict:
        """获取降级状态摘要。"""
        level = await self.get_current_level()
        config = DEGRADATION_CONFIGS[level]
        manual = await self.redis.get(self.REDIS_MANUAL_KEY)
        auto = await self.redis.get(self.REDIS_KEY)
        auto_ttl = await self.redis.ttl(self.REDIS_KEY) if auto else -1

        return {
            "current_level": level.name,
            "current_level_value": level.value,
            "is_manual": manual is not None,
            "auto_ttl_seconds": max(auto_ttl, 0),
            "config": {
                "max_iterations": config.max_iterations,
                "max_output_tokens": config.max_output_tokens,
                "allow_react": config.allow_react,
                "allow_tools": config.allow_tools,
                "allow_memory": config.allow_memory,
                "preferred_model_tier": config.preferred_model_tier,
            },
        }
