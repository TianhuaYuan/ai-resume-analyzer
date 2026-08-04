"""简历分析任务生产者。

负责将分析任务发送到 RabbitMQ，由消费者异步执行。
如果 MQ 不可用，降级为直接同步执行（走 BackgroundTasks）。
"""

import json
import logging
from typing import Optional

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

    # MQ 未启用或发送失败，同步执行
    try:
        from services.resume_analyze_consumer import process_analyze_task
        await process_analyze_task(payload)
        return True
    except Exception as e:
        logger.exception("同步分析执行失败 resume_id=%d: %s", resume_id, e)
        return False


def _now_ms() -> int:
    """获取当前毫秒时间戳。"""
    import time
    return int(time.time() * 1000)
