"""Token 限额服务。

仅在 TOKEN_QUOTA_ENABLED=True 时生效（通过环境变量控制）。
使用 Redis 记录每日消耗，key 格式: token_quota:{user_id}:{date}
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from core.config import settings
from core.redis_client import get_redis

logger = logging.getLogger(__name__)

# 使用北京时间作为时区基准
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _get_today_key(user_id: int) -> str:
    """生成今日的 Redis key。格式: token_quota:{user_id}:{YYYY-MM-DD}

    使用北京时间（Asia/Shanghai）判断"今日"。
    """
    today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    return f"token_quota:{user_id}:{today}"


def _get_seconds_until_midnight() -> int:
    """计算到明天0点（北京时间）的秒数，用于设置 Redis TTL。"""
    now = datetime.now(BEIJING_TZ)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int((tomorrow - now).total_seconds())


async def get_quota_status(user_id: int) -> dict:
    """获取用户当前的 token 限额状态。

    Returns:
        {
            "enabled": bool,           # 是否启用限额
            "used": int,               # 今日已使用
            "limit": int,              # 每日限额
            "remaining": int,          # 剩余额度
            "reset_at": str | None,    # 重置时间（ISO格式）
        }
    """
    if not settings.TOKEN_QUOTA_ENABLED:
        return {
            "enabled": False,
            "used": 0,
            "limit": settings.TOKEN_QUOTA_DAILY_LIMIT,
            "remaining": settings.TOKEN_QUOTA_DAILY_LIMIT,
            "reset_at": None,
        }

    redis = await get_redis()
    key = _get_today_key(user_id)

    if redis is None:
        logger.warning("Redis 不可用，token 限额降级为无限制")
        return {
            "enabled": True,
            "used": 0,
            "limit": settings.TOKEN_QUOTA_DAILY_LIMIT,
            "remaining": settings.TOKEN_QUOTA_DAILY_LIMIT,
            "reset_at": None,
        }

    try:
        used = await redis.get(key)
        used_tokens = int(used) if used else 0
        remaining = max(0, settings.TOKEN_QUOTA_DAILY_LIMIT - used_tokens)

        # 计算重置时间（明天0点，北京时间）
        now = datetime.now(BEIJING_TZ)
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        reset_at = tomorrow.isoformat()

        return {
            "enabled": True,
            "used": used_tokens,
            "limit": settings.TOKEN_QUOTA_DAILY_LIMIT,
            "remaining": remaining,
            "reset_at": reset_at,
        }
    except Exception as e:
        logger.error("获取 token 限额状态失败: %s", e)
        return {
            "enabled": True,
            "used": 0,
            "limit": settings.TOKEN_QUOTA_DAILY_LIMIT,
            "remaining": settings.TOKEN_QUOTA_DAILY_LIMIT,
            "reset_at": None,
        }


async def check_quota(user_id: int, estimated_tokens: int = 0) -> tuple[bool, Optional[str]]:
    """预检查用户是否有足够的 token 额度。

    Args:
        user_id: 用户ID
        estimated_tokens: 预估本次请求需要的token数（用于预检查）

    Returns:
        (是否允许, 错误消息)
        - (True, None): 允许请求
        - (False, "xxx"): 不允许，返回友好提示
    """
    if not settings.TOKEN_QUOTA_ENABLED:
        return True, None

    try:
        redis = await get_redis()
        if redis is None:
            logger.warning("Redis 不可用，跳过 token 限额检查")
            return True, None

        key = _get_today_key(user_id)
        used = await redis.get(key)
        used_tokens = int(used) if used else 0
        remaining = settings.TOKEN_QUOTA_DAILY_LIMIT - used_tokens

        # 预检查：剩余额度是否足够（预留最小额度）
        min_reserve = max(settings.TOKEN_QUOTA_MIN_RESERVE, estimated_tokens)
        if remaining < min_reserve:
            logger.info(
                "用户 %d token 额度不足: 已用 %d, 限额 %d, 剩余 %d, 需要 %d",
                user_id, used_tokens, settings.TOKEN_QUOTA_DAILY_LIMIT,
                remaining, min_reserve
            )
            return False, f"今日额度已用完，剩余 {remaining} tokens，不足以完成本次回答。额度将于明天0点自动恢复。"

        return True, None
    except Exception as e:
        logger.error("检查 token 额度失败: %s", e)
        # 出错时放行，避免影响用户体验
        return True, None


async def record_usage(user_id: int, prompt_tokens: int, completion_tokens: int) -> int:
    """记录用户的 token 消耗。

    Args:
        user_id: 用户ID
        prompt_tokens: 输入token数
        completion_tokens: 输出token数

    Returns:
        更新后的今日总使用量
    """
    if not settings.TOKEN_QUOTA_ENABLED:
        return 0

    redis = await get_redis()
    if redis is None:
        return 0

    key = _get_today_key(user_id)
    total_tokens = prompt_tokens + completion_tokens

    try:
        # 使用 INCRBY 原子递增
        new_total = await redis.incrby(key, total_tokens)

        # 如果是新key，设置过期时间（到明天0点）
        if new_total == total_tokens:
            ttl = _get_seconds_until_midnight()
            await redis.expire(key, ttl)

        logger.debug(
            "记录 token 消耗: user_id=%d, prompt=%d, completion=%d, total=%d, 今日累计=%d",
            user_id, prompt_tokens, completion_tokens, total_tokens, new_total
        )
        return new_total
    except Exception as e:
        logger.error("记录 token 消耗失败: %s", e)
        return 0