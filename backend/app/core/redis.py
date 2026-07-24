"""Redis 异步连接池配置。"""

import redis.asyncio as aioredis

from app.core.config import settings

# 创建 Redis 连接池
redis_pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=settings.REDIS_MAX_CONNECTIONS,
    decode_responses=True,
)

# Redis 客户端实例
redis_client = aioredis.Redis(connection_pool=redis_pool)


async def get_redis() -> aioredis.Redis:
    """FastAPI 依赖注入：获取 Redis 客户端。"""
    return redis_client


async def close_redis():
    """关闭 Redis 连接池。"""
    await redis_client.aclose()
