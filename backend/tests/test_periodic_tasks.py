"""周期任务机制测试：开关 / 分布式锁 / 记忆整合。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings


class TestRunLocked:
    @pytest.mark.asyncio
    async def test_executes_and_releases(self):
        """获取锁成功 → 执行 coro → 释放锁。"""
        from services.periodic_tasks import _run_locked

        called = []

        async def _coro():
            called.append(1)

        with patch(
            "services.periodic_tasks.acquire_periodic_lock",
            new_callable=AsyncMock,
            return_value="lock-1",
        ), patch(
            "services.periodic_tasks.release_periodic_lock",
            new_callable=AsyncMock,
        ) as mock_release:
            await _run_locked("test", 60, _coro)

        assert called == [1]
        mock_release.assert_awaited_once_with("test", "lock-1")

    @pytest.mark.asyncio
    async def test_skips_when_locked(self):
        """锁被其他实例持有（None）→ 不执行 coro。"""
        from services.periodic_tasks import _run_locked

        called = []

        async def _coro():
            called.append(1)

        with patch(
            "services.periodic_tasks.acquire_periodic_lock",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await _run_locked("test", 60, _coro)

        assert called == []

    @pytest.mark.asyncio
    async def test_recovers_on_coro_error(self):
        """coro 抛异常 → 记录但继续（不冒泡），锁仍释放。"""
        from services.periodic_tasks import _run_locked

        async def _coro():
            raise RuntimeError("boom")

        with patch(
            "services.periodic_tasks.acquire_periodic_lock",
            new_callable=AsyncMock,
            return_value="lock-1",
        ), patch(
            "services.periodic_tasks.release_periodic_lock",
            new_callable=AsyncMock,
        ) as mock_release:
            # 不应抛异常
            await _run_locked("test", 60, _coro)

        mock_release.assert_awaited_once()


class TestStartPeriodicTasks:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        """开关默认关闭 → 返回空列表（测试/开发零污染）。"""
        from services.periodic_tasks import start_periodic_tasks

        with patch.object(settings, "PERIODIC_TASKS_ENABLED", False):
            tasks = await start_periodic_tasks()

        assert tasks == []

    @pytest.mark.asyncio
    async def test_enabled_returns_four_tasks(self):
        """开关开启 → 返回 4 个后台 task（清理失效 + 孤儿扫描 + 过期简历 + 记忆合并）。"""
        from services.periodic_tasks import start_periodic_tasks

        with patch.object(settings, "PERIODIC_TASKS_ENABLED", True):
            tasks = await start_periodic_tasks()

        assert len(tasks) == 4
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class TestConsolidateAllMemories:
    @pytest.mark.asyncio
    async def test_filters_memory_prefix(self):
        """list_collections 过滤 memory_ 前缀，跳过 knowledge_ 等无关集合。"""
        from services.periodic_tasks import consolidate_all_memories

        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["memory_1", "memory_5", "knowledge_3"]

        with patch(
            "services.rag.clients.get_chroma_client",
            return_value=mock_client,
        ), patch(
            "services.memory.consolidation.consolidate",
            new_callable=AsyncMock,
            return_value={"expired": 0, "merged": 0, "deleted": 0, "remaining": 2},
        ) as mock_consolidate:
            await consolidate_all_memories()

        user_ids = [c.args[0] for c in mock_consolidate.await_args_list]
        assert user_ids == [1, 5]

    @pytest.mark.asyncio
    async def test_user_error_isolated(self):
        """单用户 consolidate 抛异常 → 不影响其他用户。"""
        from services.periodic_tasks import consolidate_all_memories

        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["memory_1", "memory_2"]

        async def _side_effect(user_id):
            if user_id == 1:
                raise RuntimeError("user 1 failed")
            return {"expired": 0, "merged": 0, "deleted": 0, "remaining": 1}

        with patch(
            "services.rag.clients.get_chroma_client",
            return_value=mock_client,
        ), patch(
            "services.memory.consolidation.consolidate",
            new_callable=AsyncMock,
            side_effect=_side_effect,
        ) as mock_consolidate:
            # 不应冒泡
            await consolidate_all_memories()

        assert mock_consolidate.await_count == 2
