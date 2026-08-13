"""简历分析任务生产者。

负责将分析任务发送到 RabbitMQ，由消费者异步执行。
如果 MQ 不可用，降级为直接同步执行（走 BackgroundTasks）。
"""

import logging

from core.config import settings
from core import rabbitmq_client

logger = logging.getLogger(__name__)


async def publish_analyze_task(
    resume_id: int,
    user_id: int,
    filename: str,
    priority: int = 0,
) -> bool:
    """发布分析任务到消息队列。

    Args:
        resume_id: 简历 ID
        user_id: 用户 ID
        filename: 简历文件名（用于日志追踪）
        priority: 优先级（0=普通，1=高优先级）

    Returns:
        True 发布成功，False 发布失败
    """
    payload = {
        "task": "resume_analyze",
        "resume_id": resume_id,
        "user_id": user_id,
        "filename": filename,
        "priority": priority,
        "created_at": _now_ms(),
        "retry_count": 0,
    }

    # 先尝试 RabbitMQ
    if settings.RABBITMQ_ENABLED:
        success = await rabbitmq_client.send_message(payload)
        if success:
            logger.info(
                "分析任务已发布到RabbitMQ: resume_id=%d, user_id=%d",
                resume_id, user_id,
            )
            return True
        logger.warning(
            "RabbitMQ 发送失败，降级为同步执行: resume_id=%d", resume_id
        )
        # 不 return False，继续往下走到同步执行

    # MQ 未启用或发送失败，降级为后台异步执行。
    # 原实现 `await process_analyze_task` 同步内联——MQ 掉线时 4×90s 的分析
    # 会阻塞调用方（process_resume_background 解析完成后等分析做完才返回）。
    # 改为 asyncio.create_task 后台执行，调用方立即返回，不阻塞解析主流程。
    import asyncio

    try:
        from services.resume_analyze_consumer import process_analyze_task
        # Test runs use an in-process database and ASGI transport; await the
        # fallback there so the upload→ready contract is deterministic.  Real
        # environments keep the non-blocking background path for latency.
        if settings.ENVIRONMENT == "testing":
            await process_analyze_task(payload)
            logger.info(
                "测试环境同步完成分析任务 resume_id=%d", resume_id
            )
            return True
        asyncio.create_task(process_analyze_task(payload))
        logger.info(
            "MQ 降级：分析任务已转为后台任务 resume_id=%d", resume_id
        )
        return True
    except Exception as e:
        logger.exception("后台分析任务调度失败 resume_id=%d: %s", resume_id, e)
        return False


def _now_ms() -> int:
    """获取当前毫秒时间戳。"""
    import time
    return int(time.time() * 1000)
