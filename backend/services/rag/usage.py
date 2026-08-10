"""LLM 调用统一记账服务。

记录全量 LLM 调用的 token 消耗（prompt / completion / total / call_count），
按用户+日期聚合到 Redis（7 天 TTL）。

设计原则：
- 只记成功调用（调用方保证在成功后才调用）
- Redis 挂时降级为 InMemoryRedis，不阻塞主流程
- 失败日志限频（60s 内最多一条），避免日志爆炸
"""

import logging
import time
from datetime import datetime, timezone

from core.redis_client import get_redis
from core.config import settings

logger = logging.getLogger(__name__)

# 失败日志限频：连续 Redis 故障时减少日志噪音
_LAST_FAIL_LOG_TIME: float = 0.0
_FAIL_LOG_INTERVAL_SEC: int = 60


async def record_llm_usage(
    user_id: int,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    model: str | None = None,
) -> None:
    """记录 LLM token 使用量到 Redis（日统计）。

    Args:
        user_id: 用户 ID
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数

    Redis Key 格式（string，incrby）：
        llm_usage:{user_id}:{YYYYMMDD}:prompt
        llm_usage:{user_id}:{YYYYMMDD}:completion
        llm_usage:{user_id}:{YYYYMMDD}:total
        llm_usage:{user_id}:{YYYYMMDD}:calls

    TTL: 7 天
    """
    if prompt_tokens < 0 or completion_tokens < 0:
        return

    total = prompt_tokens + completion_tokens
    if total <= 0:
        return

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    base = f"llm_usage:{user_id}:{date_str}"

    try:
        redis = await get_redis()
        # 并行递增 4 个计数器（InMemoryRedis 不支持 pipeline，逐个调用）
        await redis.incrby(f"{base}:prompt", prompt_tokens)
        await redis.incrby(f"{base}:completion", completion_tokens)
        await redis.incrby(f"{base}:total", total)
        await redis.incrby(f"{base}:calls", 1)

        # 成本以微美元整数累计，避免 Redis 浮点误差；费率为 0 时仍保留 token 统计。
        input_rate = max(0.0, float(getattr(settings, "LLM_INPUT_COST_PER_MILLION_USD", 0.0)))
        output_rate = max(0.0, float(getattr(settings, "LLM_OUTPUT_COST_PER_MILLION_USD", 0.0)))
        input_micro_usd = round(prompt_tokens * input_rate)
        output_micro_usd = round(completion_tokens * output_rate)
        if input_micro_usd:
            await redis.incrby(f"{base}:cost_input_micro_usd", input_micro_usd)
        if output_micro_usd:
            await redis.incrby(f"{base}:cost_output_micro_usd", output_micro_usd)
        if input_micro_usd or output_micro_usd:
            await redis.incrby(
                f"{base}:cost_total_micro_usd",
                input_micro_usd + output_micro_usd,
            )

        # 设置 7 天过期（对新 key 生效，已存在的 key 续期不影响）
        ttl = 86400 * 7
        await redis.expire(f"{base}:prompt", ttl)
        await redis.expire(f"{base}:completion", ttl)
        await redis.expire(f"{base}:total", ttl)
        await redis.expire(f"{base}:calls", ttl)
        for suffix in ("cost_input_micro_usd", "cost_output_micro_usd", "cost_total_micro_usd"):
            await redis.expire(f"{base}:{suffix}", ttl)
    except Exception:
        _log_redis_fail_limited()


async def get_usage_summary(days: int = 7) -> list[dict]:
    """D4: 读取近 N 天 LLM 用量（按天聚合，跨全部用户）。

    Redis Key 格式：llm_usage:{user_id}:{YYYYMMDD}:{prompt|completion|total|calls}
    通过 scan 收集 total/calls 后缀的 key，按日期聚合。

    Returns:
        形如 [{"date": "20260804", "total_tokens": 123, "calls": 5}, ...]，
        按日期升序；Redis 不可用返回空列表
    """
    try:
        redis = await get_redis()
        keys = await redis.keys("llm_usage:*:*:total")
        if not keys:
            return []
    except Exception:
        _log_redis_fail_limited()
        return []

    # 解析 key → (date, total/calls 值)，跨用户聚合
    merged: dict[str, dict] = {}
    for key in keys:
        parts = key.split(":")
        if len(parts) < 4:
            continue
        date_str = parts[-2]  # llm_usage:{user_id}:{date}:total
        try:
            value = int(await redis.get(key) or 0)
        except Exception:
            value = 0
        entry = merged.setdefault(
            date_str,
            {
                "date": date_str,
                "total_tokens": 0,
                "calls": 0,
                "cost_usd": 0.0,
            },
        )
        entry["total_tokens"] += value

        # 对应的 calls 计数
        calls_key = ":".join(parts[:-1] + ["calls"])
        try:
            calls = int(await redis.get(calls_key) or 0)
        except Exception:
            calls = 0
        entry["calls"] += calls

        cost_key = ":".join(parts[:-1] + ["cost_total_micro_usd"])
        try:
            entry["cost_usd"] += int(await redis.get(cost_key) or 0) / 1_000_000
        except Exception:
            pass

    return [merged[d] for d in sorted(merged)]


def _log_redis_fail_limited() -> None:
    """限频记录 Redis 降级日志。"""
    global _LAST_FAIL_LOG_TIME
    now = time.time()
    if now - _LAST_FAIL_LOG_TIME >= _FAIL_LOG_INTERVAL_SEC:
        _LAST_FAIL_LOG_TIME = now
        logger.warning("Redis 不可用，LLM usage 记账降级（限频日志，每 %ds 一次）", _FAIL_LOG_INTERVAL_SEC)
