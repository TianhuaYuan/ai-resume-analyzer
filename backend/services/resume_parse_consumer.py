"""简历解析任务消费者。

由 RabbitMQ 消费者触发，执行流程：
1. 调 process_resume_background（三阶段解析，内部更新 parse_progress + WebSocket 推送）
2. 失败且未达最大重试次数 → 重新入队（retry_count + 1）
3. 超过最大重试次数 → 记错误日志（DB 已由 process_resume_background 标记 failed，
   用户可手动重试 retry 端点）

与 resume_analyze_consumer 的区别：解析任务不涉及分布式锁/Redis 幂等/token 限额，
重试语义由消息队列入队实现（而非进程内循环），保证重启后任务不丢。
"""

import logging

from core import rabbitmq_client

logger = logging.getLogger(__name__)

# 最大重试次数（达到后不再重新入队，DB 标记 failed，等待用户手动重试）
MAX_PARSE_RETRY = 2


async def process_parse_task(payload: dict) -> None:
    """处理单个解析任务。

    此函数可被：
    - RabbitMQ 消费者直接调用（经 main.py 的 task 分发 handler）
    - 直接调用（测试 / 手动触发）

    Args:
        payload: 消息体，包含 resume_id, user_id, file_path, retry_count
    """
    resume_id = payload.get("resume_id")
    user_id = payload.get("user_id", 0)
    file_path = payload.get("file_path")
    retry_count = payload.get("retry_count", 0)

    if resume_id is None or not file_path:
        logger.error("解析任务缺少必要参数: %s", payload)
        return

    from services import resume_service

    ok = await resume_service.process_resume_background(
        resume_id, file_path, user_id
    )
    if ok:
        return

    # 处理失败：未达上限 → 重新入队重试
    if retry_count < MAX_PARSE_RETRY:
        retry_payload = {**payload, "retry_count": retry_count + 1}
        re_sent = await rabbitmq_client.send_message(retry_payload)
        if re_sent:
            logger.warning(
                "解析失败，已重新入队重试: resume_id=%d, retry=%d/%d",
                resume_id, retry_count + 1, MAX_PARSE_RETRY,
            )
        else:
            logger.warning(
                "解析失败且重试入队失败（MQ 不可用），不再重试: resume_id=%d",
                resume_id,
            )
    else:
        logger.error(
            "解析失败已达最大重试次数 %d，标记 failed 等待手动重试: resume_id=%d",
            MAX_PARSE_RETRY, resume_id,
        )
