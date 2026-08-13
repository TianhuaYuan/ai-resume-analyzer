"""A3 记忆增强测试（ 隐藏 + graphiti 失效不删除）。

覆盖：
- expire_memory → update_metadata 标记 expired，不删除
- recall_memory 默认隐藏 expired / show_expired 可见
- consolidate 过期 → 标记而非物理删除（delete 不被调用）
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.memory.consolidation import consolidate
from services.memory.memory_store import MEM_EXPIRED, expire_memory, recall_memory


def _fake_item(mid: str, text: str, score: float, meta: dict) -> dict:
    return {"id": mid, "text": text, "score": score, "metadata": meta}


@pytest.mark.asyncio
async def test_expire_memory_marks_not_deletes():
    """expire_memory → update_metadata(expired=true)，不调 delete。"""
    fake_store = MagicMock()
    fake_store.update_metadata = AsyncMock()
    fake_store.delete = AsyncMock()

    with patch("services.memory.memory_store.get_vector_store", return_value=fake_store):
        await expire_memory(1, "abc123")

    fake_store.update_metadata.assert_awaited_once()
    kwargs = fake_store.update_metadata.await_args.kwargs
    assert kwargs["ids"] == ["abc123"]
    assert kwargs["metadatas"][0][MEM_EXPIRED] is True
    fake_store.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_recall_hides_expired_by_default():
    """默认召回过滤 expired 记忆。"""
    fake_store = MagicMock()
    fake_store.query = AsyncMock(return_value=[
        _fake_item("live", "活跃记忆", 0.9, {}),
        _fake_item("dead", "失效记忆", 0.95, {MEM_EXPIRED: True}),
    ])

    with patch("services.memory.memory_store.get_vector_store", return_value=fake_store), \
         patch("services.memory.memory_store.get_embeddings", new_callable=AsyncMock,
               return_value=[[0.1] * 8]):
        result = await recall_memory(user_id=1, query="测试")

    assert len(result) == 1
    assert result[0]["memory_id"] == "live"


@pytest.mark.asyncio
async def test_recall_show_expired_includes_dead():
    """show_expired=True 时失效记忆可见（审计/回溯）。"""
    fake_store = MagicMock()
    fake_store.query = AsyncMock(return_value=[
        _fake_item("dead", "失效记忆", 0.95, {MEM_EXPIRED: True}),
    ])

    with patch("services.memory.memory_store.get_vector_store", return_value=fake_store), \
         patch("services.memory.memory_store.get_embeddings", new_callable=AsyncMock,
               return_value=[[0.1] * 8]):
        result = await recall_memory(user_id=1, query="测试", show_expired=True)

    assert len(result) == 1
    assert result[0]["memory_id"] == "dead"


@pytest.mark.asyncio
async def test_consolidate_marks_expired_instead_of_delete():
    """consolidate 过期 → expire_memory 标记（delete 仅用于重复合并）。"""
    fake_store = MagicMock()
    fake_store.get = AsyncMock(return_value=[
        _fake_item("old", "过期记忆", 0.0, {"ttl": 100, "last_accessed_at": 0}),  # 过期
        _fake_item("live", "活跃记忆", 0.0, {}),
    ])
    fake_store.update_metadata = AsyncMock()
    fake_store.delete = AsyncMock()

    with patch("services.memory.memory_store.get_vector_store", return_value=fake_store), \
         patch("services.memory.consolidation.get_vector_store", return_value=fake_store), \
         patch("services.memory.consolidation.get_embeddings", new_callable=AsyncMock,
               return_value=[[0.1] * 8, [0.1] * 8]):
        stats = await consolidate(1)

    # 过期 → 标记（update_metadata 而非 delete）
    fake_store.update_metadata.assert_awaited()
    assert stats["expired"] == 1
    assert stats["deleted"] == 0  # 无重复合并 → 无物理删除
    assert stats["remaining"] == 2  # 过期不删除，数据保留


@pytest.mark.asyncio
async def test_consolidate_duplicates_still_deleted():
    """重复合并仍是物理删除（重复不是历史）。"""
    fake_store = MagicMock()
    fake_store.get = AsyncMock(return_value=[
        _fake_item("a", "同一内容A", 0.0, {"importance": 0.9}),
        _fake_item("b", "同一内容B", 0.0, {"importance": 0.3}),
    ])
    fake_store.delete = AsyncMock()

    with patch("services.memory.memory_store.get_vector_store", return_value=fake_store), \
         patch("services.memory.consolidation.get_vector_store", return_value=fake_store), \
         patch("services.memory.consolidation.get_embeddings", new_callable=AsyncMock,
               return_value=[[0.1] * 8, [0.1] * 8]):  # 余弦=1 → 重复
        stats = await consolidate(1)

    assert stats["merged"] == 1
    assert stats["deleted"] == 1
    assert stats["expired"] == 0
