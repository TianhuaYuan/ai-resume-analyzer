"""Tests for RabbitMQ message queue client (core/rabbitmq_client.py).

RED-GREEN-REFACTOR cycle:
1. RED: Module didn't exist → ImportError
2. GREEN: Created core/rabbitmq_client.py
3. Now: Verify all tests pass, then REFACTOR
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestRabbitMQClient:
    """RabbitMQ 客户端测试套件。"""

    async def test_init_producer_skipped_in_dev(self):
        """dev 环境直接跳过生产者初始化。"""
        import core.rabbitmq_client as rmq
        rmq._reset()

        with patch("core.rabbitmq_client.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "development"
            result = await rmq.init_producer()
            assert result is False

    async def test_init_producer_skipped_in_test(self):
        """test 环境直接跳过生产者初始化。"""
        import core.rabbitmq_client as rmq
        rmq._reset()

        with patch("core.rabbitmq_client.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "testing"
            result = await rmq.init_producer()
            assert result is False

    async def test_init_producer_disabled(self):
        """RABBITMQ_ENABLED=False 时跳过。"""
        import core.rabbitmq_client as rmq
        rmq._reset()

        with patch("core.rabbitmq_client.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "staging"
            mock_settings.RABBITMQ_ENABLED = False
            result = await rmq.init_producer()
            assert result is False

    @patch("aio_pika.connect_robust", new_callable=AsyncMock)
    async def test_init_producer_success(self, mock_connect):
        """连接 RabbitMQ 成功后返回 True。"""
        import core.rabbitmq_client as rmq
        rmq._reset()

        mock_conn = AsyncMock()
        mock_channel = AsyncMock()
        mock_connect.return_value = mock_conn
        mock_conn.channel.return_value = mock_channel

        with patch("core.rabbitmq_client.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "staging"
            mock_settings.RABBITMQ_ENABLED = True
            mock_settings.RABBITMQ_URL = "amqp://guest:guest@localhost:5672/"
            mock_settings.RABBITMQ_QUEUE = "ai_resume_analyze"

            result = await rmq.init_producer()

            assert result is True
            mock_connect.assert_called_once_with("amqp://guest:guest@localhost:5672/")

    @patch("aio_pika.connect_robust", new_callable=AsyncMock)
    async def test_init_producer_connection_failure(self, mock_connect):
        """连接失败时返回 False。"""
        import core.rabbitmq_client as rmq
        rmq._reset()

        mock_connect.side_effect = ConnectionError("RabbitMQ unavailable")

        with patch("core.rabbitmq_client.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "staging"
            mock_settings.RABBITMQ_ENABLED = True
            mock_settings.RABBITMQ_URL = "amqp://guest:guest@localhost:5672/"
            mock_settings.RABBITMQ_QUEUE = "ai_resume_analyze"

            result = await rmq.init_producer()

            assert result is False

    async def test_init_consumer_skipped_in_dev(self):
        """dev 环境跳过消费者初始化。"""
        import core.rabbitmq_client as rmq
        rmq._reset()

        with patch("core.rabbitmq_client.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "development"
            result = await rmq.init_consumer(lambda _: None)
            assert result is False

    @patch("aio_pika.connect_robust", new_callable=AsyncMock)
    async def test_init_consumer_success(self, mock_connect):
        """启动消费者成功返回 True。"""
        import core.rabbitmq_client as rmq
        rmq._reset()

        mock_conn = AsyncMock()
        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_connect.return_value = mock_conn
        mock_conn.channel.return_value = mock_channel
        mock_channel.declare_queue.return_value = mock_queue

        with patch("core.rabbitmq_client.settings") as mock_settings:
            mock_settings.ENVIRONMENT = "staging"
            mock_settings.RABBITMQ_ENABLED = True
            mock_settings.RABBITMQ_URL = "amqp://guest:guest@localhost:5672/"
            mock_settings.RABBITMQ_QUEUE = "ai_resume_analyze"

            handler = AsyncMock()
            result = await rmq.init_consumer(handler)

            assert result is True
            mock_connect.assert_called_once()
            mock_queue.consume.assert_called_once()

    async def test_send_message_not_initialized(self):
        """未初始化时发送消息返回 False。"""
        import core.rabbitmq_client as rmq
        rmq._reset()

        with patch("core.rabbitmq_client.settings") as mock_settings:
            mock_settings.RABBITMQ_ENABLED = True

            result = await rmq.send_message({"resume_id": 1})
            assert result is False

    async def test_send_message_success(self):
        """发送消息成功返回 True。"""
        import core.rabbitmq_client as rmq
        rmq._reset()

        mock_channel = AsyncMock()

        with (
            patch("core.rabbitmq_client.settings") as mock_settings,
            patch("core.rabbitmq_client._channel", mock_channel),
        ):
            mock_settings.RABBITMQ_ENABLED = True
            mock_settings.RABBITMQ_QUEUE = "ai_resume_analyze"

            result = await rmq.send_message({"resume_id": 1, "user_id": 42})

            assert result is True
            mock_channel.default_exchange.publish.assert_called_once()

    async def test_shutdown_closes_connection(self):
        """shutdown 关闭连接并清理状态。"""
        import core.rabbitmq_client as rmq

        mock_conn = AsyncMock()
        rmq._connection = mock_conn
        rmq._channel = AsyncMock()

        await rmq.shutdown()

        mock_conn.close.assert_called_once()
        assert rmq._connection is None
        assert rmq._channel is None

    async def test_shutdown_idempotent(self):
        """多次 shutdown 安全。"""
        import core.rabbitmq_client as rmq
        rmq._connection = None
        rmq._channel = None

        await rmq.shutdown()
        await rmq.shutdown()
