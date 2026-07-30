"""验证码服务。

功能：
- 生成 6 位数字验证码
- 存储验证码（Redis 或内存降级）
- 验证验证码
- 清除验证码

环境适配：
- Redis 可用 → 使用 Redis（生产环境）
- Redis 不可用 → 使用内存字典（开发/测试环境）
"""
import logging
import random
import string
from datetime import datetime, timedelta
from typing import Optional

from core.config import settings
from core.redis_client import get_redis

logger = logging.getLogger(__name__)

_CODE_EXPIRE_MINUTES = 5
_CODE_KEY_PREFIX = "verify_code:"


def generate_code(length: int = 6) -> str:
    """生成指定长度的数字验证码。"""
    return "".join(random.choices(string.digits, k=length))


_in_memory_codes: dict[str, dict[str, str | datetime]] = {}


async def store_code(email: str, code: str) -> None:
    """存储验证码。优先使用 Redis/InMemoryRedis，同时写入 fallback 内存字典。"""
    redis = await get_redis()
    expire_seconds = _CODE_EXPIRE_MINUTES * 60
    key = f"{_CODE_KEY_PREFIX}{email}"

    # 优先用 Redis（可能返回 InMemoryRedis 实例）
    if redis is not None:
        await redis.setex(key, expire_seconds, code)

    # 同时始终写入 fallback 内存字典（测试/热重载场景可读）
    _in_memory_codes[key] = {
        "code": code,
        "expire_at": datetime.now() + timedelta(minutes=_CODE_EXPIRE_MINUTES),
    }

    logger.debug(
        "验证码已存储: email=%s, backend=%s",
        email, "redis" if redis is not None else "memory",
    )


async def verify_code(email: str, code: str) -> bool:
    """验证验证码。验证成功后自动清除。"""
    redis = await get_redis()
    key = f"{_CODE_KEY_PREFIX}{email}"

    stored_code: Optional[str] = None

    if redis is not None:
        stored_code = await redis.get(key)
    else:
        entry = _in_memory_codes.get(key)
        if entry:
            expire_at = entry["expire_at"]
            if datetime.now() <= expire_at:
                stored_code = entry["code"]
            else:
                del _in_memory_codes[key]

    if stored_code is None or stored_code != code:
        logger.debug("验证码验证失败: email=%s", email)
        return False

    await clear_code(email)
    logger.debug("验证码验证成功: email=%s", email)
    return True


async def clear_code(email: str) -> None:
    """清除验证码（Redis + 内存同时清理）。"""
    redis = await get_redis()
    key = f"{_CODE_KEY_PREFIX}{email}"

    if redis is not None:
        await redis.delete(key)
    _in_memory_codes.pop(key, None)

    logger.debug("验证码已清除: email=%s", email)