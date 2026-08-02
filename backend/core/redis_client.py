"""Redis 连接单例，含降级策略。

Redis 不可用时自动降级为 InMemoryRedis，所有功能原地工作。
"""

import asyncio
import logging
import time

from core.config import settings

logger = logging.getLogger(__name__)

_redis = None
_in_memory = None
# Redis 降级冷却期：连接失败后 _REDIS_RETRY_AFTER 秒内直接走内存降级，不重试
_redis_down_until = 0.0
_REDIS_RETRY_AFTER = 30.0


class InMemoryRedis:
    """内存版 Redis，实现应用所需的 Redis 接口子集。

    数据存储在 dict + expire_at 字典，支持 TTL 过期。
    完全兼容 redis.asyncio.Redis 的调用方式。
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expire_at: dict[str, float] = {}

    def _purge_expired(self) -> None:
        """清除已过期的 key。"""
        now = time.time()
        expired = [k for k, t in self._expire_at.items() if t <= now]
        for k in expired:
            self._data.pop(k, None)
            self._expire_at.pop(k, None)

    def _is_valid(self, key: str) -> bool:
        """检查 key 是否未过期。"""
        expiry = self._expire_at.get(key)
        if expiry is not None and expiry <= time.time():
            self._data.pop(key, None)
            self._expire_at.pop(key, None)
            return False
        return key in self._data

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        self._purge_expired()
        val = self._data.get(key)
        return val if val is not None else None

    async def set(
        self, key: str, value: str, nx: bool = False, ex: int | None = None
    ) -> bool:
        if nx and key in self._data and self._is_valid(key):
            return False
        self._data[key] = value
        if ex is not None:
            self._expire_at[key] = time.time() + ex

        # 模拟异步非阻塞写入
        await asyncio.sleep(0)
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        self._data[key] = value
        self._expire_at[key] = time.time() + seconds
        await asyncio.sleep(0)

    async def incrby(self, key: str, amount: int) -> int:
        self._purge_expired()
        raw = self._data.get(key, "0")
        try:
            current = int(raw)
        except (ValueError, TypeError):
            current = 0
        new_value = current + amount
        self._data[key] = str(new_value)
        await asyncio.sleep(0)
        return new_value

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self._data:
            return False
        self._expire_at[key] = time.time() + seconds
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                self._expire_at.pop(k, None)
                count += 1
        await asyncio.sleep(0)
        return count

    async def mget(self, *keys: str) -> list[str | None]:
        self._purge_expired()
        return [self._data.get(k) for k in keys]

    async def eval(self, script: str, num_keys: int, *args: str) -> int:
        """简易 Lua eval — 按脚本内容区分 RELEASE（DEL）与 RENEW（EXPIRE）。

        真实 Redis 的 eval 会完整执行 Lua；内存实现只覆盖 edit_lock 用到的两个脚本：
        - _RELEASE_SCRIPT（含 "DEL"）：GET == ARGV[1] 则 DEL，返回 1
        - _RENEW_SCRIPT（含 "EXPIRE"）：GET == ARGV[1] 则续期 TTL，返回 1
        其余脚本一律返回 0（保守行为，避免误删/误改）。

        修复背景：原实现把所有脚本都当 DEL 执行，导致续期（EXPIRE）时把锁删了，
        后续心跳全部 409。
        """
        if num_keys > 0 and args:
            key = args[0]
            expected = args[1] if len(args) > 1 else None
            current = self._data.get(key)
            if current is not None and current == expected:
                if "EXPIRE" in script:
                    # RENEW：续期 TTL（args[2] = 新 TTL 秒数）
                    ttl = int(args[2]) if len(args) > 2 else 120
                    self._expire_at[key] = time.time() + ttl
                    return 1
                if "DEL" in script:
                    del self._data[key]
                    self._expire_at.pop(key, None)
                    return 1
        return 0


async def get_redis():
    """获取 Redis 客户端。不可用时返回 InMemoryRedis 实例。

    性能护栏（T17）：Redis 不可用时进入「降级冷却期」——冷却期内直接返回
    InMemoryRedis，不再每次调用都重试连接。否则每次 Redis 访问都白付
    socket_connect_timeout 的连接超时（本机 Redis 未启动时 = 每次 2s+ 延迟，
    会让每个 agent 交互凭空多出数秒）。
    """
    global _redis, _in_memory, _redis_down_until

    now = time.time()

    # 冷却期内：Redis 刚失败过，直接内存降级，不再重试
    if _redis is None and now < _redis_down_until:
        if _in_memory is None:
            _in_memory = InMemoryRedis()
        return _in_memory

    # 已有真实 Redis 连接且可用
    if _redis is not None:
        try:
            await _redis.ping()
            return _redis
        except Exception:
            _redis = None
            _redis_down_until = now + _REDIS_RETRY_AFTER
            logger.warning("Redis 连接断开，进入降级冷却期")

    # 尝试连接真实 Redis
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        await _redis.ping()
        logger.info("Redis connected at %s", settings.REDIS_URL)
        return _redis
    except Exception:
        _redis = None
        _redis_down_until = now + _REDIS_RETRY_AFTER
        logger.info("Redis unavailable, in-memory fallback (cooldown %ds)", _REDIS_RETRY_AFTER)

    # 降级为 InMemoryRedis
    if _in_memory is None:
        _in_memory = InMemoryRedis()
    return _in_memory


async def close_redis():
    """关闭 Redis 连接。"""
    global _redis, _in_memory
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None
    _in_memory = None
