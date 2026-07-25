"""Redis 连接单例，含降级策略。

Redis 不可用时返回 None，调用方自行降级为内存模式。
"""

import logging

logger = logging.getLogger(__name__)

_redis = None


async def get_redis():
    """获取 Redis 客户端。不可用时返回 None，调用方自行降级。"""
    global _redis
    if _redis is not None:
        try:
            await _redis.ping()
            return _redis
        except Exception:
            _redis = None

    try:
        import redis.asyncio as aioredis

        from core.config import settings

        _redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await _redis.ping()
        logger.info("Redis connected")
        return _redis
    except Exception:
        logger.warning("Redis unavailable, using in-memory fallback")
        return None


async def close_redis():
    """关闭 Redis 连接。"""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
