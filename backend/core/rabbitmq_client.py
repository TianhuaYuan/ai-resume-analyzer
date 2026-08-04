"""RabbitMQ 消息队列客户端。

基于 aio-pika 库实现，支持异步连接、消息发布和消费。
降级策略（按环境）：
- development/testing：按 ENVIRONMENT 标签直接跳过，零开销
- staging/production：尝试连接，失败后降级为同步执行
"""

import json
import logging
from typing import Callable, Awaitable

from core.config import settings

logger = logging.getLogger(__name__)

_connection = None
_channel = None
_consumer_tag = None
# 协作停止标志（JobHunter set_stop_check/should_stop 对照）：
# 应用关闭时置位，消费者循环检查后停止拉新消息，避免 shutdown 截断正在处理的任务
_stop_requested = False


def _reset() -> None:
    """重置全局状态（仅测试用）。"""
    global _connection, _channel, _consumer_tag, _stop_requested
    _connection = None
    _channel = None
    _consumer_tag = None
    _stop_requested = False


def request_stop() -> None:
    """请求协作停止（main.py lifespan shutdown 时调用，优先于关连接）。"""
    global _stop_requested
    _stop_requested = True
    logger.info("RabbitMQ 协作停止已请求（不再消费新消息）")


def should_stop() -> bool:
    """协作停止检查（JobHunter should_stop 对照）：消费者循环内每消息检查。"""
    return _stop_requested


async def init_producer() -> bool:
    """初始化 RabbitMQ 生产者和队列。

    Returns:
        True 初始化成功，False 跳过或失败
    """
    global _connection, _channel

    if settings.ENVIRONMENT in ("development", "testing"):
        return False

    if not settings.RABBITMQ_ENABLED:
        logger.info("RabbitMQ 未启用，跳过生产者初始化")
        return False

    if _channel is not None:
        return True

    try:
        import aio_pika

        _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        _channel = await _connection.channel()
        await _channel.declare_queue(settings.RABBITMQ_QUEUE, durable=True)
        logger.info("RabbitMQ 生产者初始化成功")
        return True

    except Exception as e:
        logger.error("RabbitMQ 生产者初始化失败: %s", e)
        _connection = None
        _channel = None
        return False


async def init_consumer(
    message_handler: Callable[[dict], Awaitable[None]],
) -> bool:
    """初始化 RabbitMQ 消费者，开始消费队列消息。

    Args:
        message_handler: 消息处理回调 async def handler(message: dict) -> None

    Returns:
        True 初始化成功，False 跳过或失败
    """
    global _connection, _channel, _consumer_tag

    if settings.ENVIRONMENT in ("development", "testing"):
        return False

    if not settings.RABBITMQ_ENABLED:
        logger.info("RabbitMQ 未启用，跳过消费者初始化")
        return False

    if _consumer_tag is not None:
        return True

    try:
        import aio_pika

        _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        _channel = await _connection.channel()
        queue = await _channel.declare_queue(settings.RABBITMQ_QUEUE, durable=True)

        # 注册消息处理回调
        async def _on_message(message: aio_pika.IncomingMessage) -> None:
            # 协作停止（JobHunter should_stop 对照）：shutdown 已请求 → 拒绝新消息（reject 回队列）
            if _stop_requested:
                await message.reject(requeue=True)
                return
            async with message.process():
                try:
                    body = json.loads(message.body.decode("utf-8"))
                    await message_handler(body)
                except Exception as e:
                    logger.exception("RabbitMQ 消息消费失败: %s", e)

        _consumer_tag = await queue.consume(_on_message)
        logger.info("RabbitMQ 消费者初始化成功，队列: %s", settings.RABBITMQ_QUEUE)
        return True

    except Exception as e:
        logger.error("RabbitMQ 消费者初始化失败: %s", e)
        _connection = None
        _channel = None
        _consumer_tag = None
        return False


async def send_message(payload: dict) -> bool:
    """发送消息到 RabbitMQ 队列。

    Args:
        payload: 消息体（字典，会被 JSON 序列化）

    Returns:
        True 发送成功，False 发送失败或未启用
    """
    if not settings.RABBITMQ_ENABLED:
        logger.debug("RabbitMQ 未启用，跳过消息发送")
        return False

    if _channel is None:
        logger.warning("RabbitMQ 未初始化，跳过消息发送")
        return False

    try:
        import aio_pika

        message = aio_pika.Message(
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await _channel.default_exchange.publish(
            message,
            routing_key=settings.RABBITMQ_QUEUE,
        )
        logger.info(
            "RabbitMQ 消息发送成功: resume_id=%s",
            payload.get("resume_id"),
        )
        return True

    except Exception as e:
        logger.error("RabbitMQ 消息发送失败: %s", e)
        return False


async def shutdown() -> None:
    """关闭 RabbitMQ 连接和频道。

    先发协作停止（JobHunter 对照）：消费者拒绝新消息（requeue），
    正在处理的消息不被 shutdown 截断。
    """
    global _connection, _channel, _consumer_tag

    request_stop()
    _consumer_tag = None
    _channel = None

    if _connection is not None:
        try:
            await _connection.close()
            logger.info("RabbitMQ 连接已关闭")
        except Exception as e:
            logger.warning("关闭 RabbitMQ 连接失败: %s", e)
        _connection = None
