"""删除闭环修复测试：BM25 清理 / 账户级联 / 孤儿扫描 memory_* 覆盖。

覆盖修复：
- clear_bm25：多资产 scope key（``{user_id}:[1,2]``）精确删除，公共 market key 不受影响
- clear_user_bm25：账户删除时清该用户全部 scope 组合
- delete_user_account：删现行命名 knowledge_{uid} + memory_{uid} 集合，
  逐简历清 Redis 分析缓存 + Embedding 缓存 + BM25，不再误用旧命名 resume_{rid}
- orphan_scan：识别用户已不存在的 memory_{user_id} 孤儿集合
"""

import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from services.rag import retrieval
from services.user_cleanup_service import delete_user_account


def asynccontextmanager_mock(mock_db):
    """创建异步上下文管理器 mock，用于 AsyncSessionLocal（对齐 test_t6 的 helper）。"""
    class _MockSession:
        async def __aenter__(self):
            return mock_db
        async def __aexit__(self, *args):
            pass
    return _MockSession()


# ═══════════════════════════════════════════════════════════
# clear_bm25：多资产 scope key 清理
# ═══════════════════════════════════════════════════════════


class TestClearBm25:
    @pytest.mark.asyncio
    async def test_clears_single_and_multi_asset_keys(self):
        """删单个资产应同时清掉含该资产的所有 scope 组合 key。"""
        retrieval._bm25_indexes.clear()
        retrieval._bm25_indexes["1:[2]"] = (None, [])
        retrieval._bm25_indexes["1:[1,2]"] = (None, [])
        retrieval._bm25_indexes["1:[1,2,3]"] = (None, [])
        retrieval._bm25_indexes["1:[3]"] = (None, [])  # 不含 asset 2 → 应保留

        await retrieval.clear_bm25(1, 2)

        assert "1:[2]" not in retrieval._bm25_indexes
        assert "1:[1,2]" not in retrieval._bm25_indexes
        assert "1:[1,2,3]" not in retrieval._bm25_indexes
        assert "1:[3]" in retrieval._bm25_indexes
        retrieval._bm25_indexes.clear()

    @pytest.mark.asyncio
    async def test_keeps_other_user_and_market_keys(self):
        """其他用户 key 与公共 market key 不应被误删。"""
        retrieval._bm25_indexes.clear()
        retrieval._bm25_indexes["1:[2]"] = (None, [])
        retrieval._bm25_indexes["2:[2]"] = (None, [])  # 其他用户
        retrieval._bm25_indexes["market:market_public:[2]"] = (None, [])  # 公共集合

        await retrieval.clear_bm25(1, 2)

        assert "1:[2]" not in retrieval._bm25_indexes
        assert "2:[2]" in retrieval._bm25_indexes
        assert "market:market_public:[2]" in retrieval._bm25_indexes
        retrieval._bm25_indexes.clear()


# ═══════════════════════════════════════════════════════════
# clear_user_bm25：账户删除全量清理
# ═══════════════════════════════════════════════════════════


class TestClearUserBm25:
    @pytest.mark.asyncio
    async def test_clears_all_scope_keys_of_user(self):
        """清某用户全部 scope 组合 key，不影响其他用户与公共集合。"""
        retrieval._bm25_indexes.clear()
        retrieval._bm25_indexes["1:[1,2]"] = (None, [])
        retrieval._bm25_indexes["1:[3]"] = (None, [])
        retrieval._bm25_indexes["2:[1]"] = (None, [])  # 其他用户
        retrieval._bm25_indexes["market:market_public:[1]"] = (None, [])  # 公共集合

        await retrieval.clear_user_bm25(1)

        assert "1:[1,2]" not in retrieval._bm25_indexes
        assert "1:[3]" not in retrieval._bm25_indexes
        assert "2:[1]" in retrieval._bm25_indexes
        assert "market:market_public:[1]" in retrieval._bm25_indexes
        retrieval._bm25_indexes.clear()


# ═══════════════════════════════════════════════════════════
# delete_user_account：账户删除完整清理链
# ═══════════════════════════════════════════════════════════


class TestDeleteUserAccount:
    @pytest.mark.asyncio
    async def test_cleans_vectors_caches_files_and_db(self):
        """删现行命名 knowledge_{uid} + memory_{uid} 集合，清缓存、文件、DB 级联。"""
        resume1 = MagicMock(id=1, file_path="/tmp/a.pdf")
        resume2 = MagicMock(id=2, file_path="/tmp/b.pdf")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [resume1, resume2]
        mock_db.execute.return_value = mock_result
        mock_user = MagicMock(id=10)

        with patch(
            "services.user_cleanup_service.get_vector_store",
            return_value=MagicMock(delete_collection=AsyncMock()),
        ) as mock_vs, \
             patch("services.user_cleanup_service.invalidate_resume_cache", new_callable=AsyncMock) as mock_inv, \
             patch("services.user_cleanup_service.embedding_cache.clear_resume", new_callable=AsyncMock) as mock_emb, \
             patch("services.user_cleanup_service.clear_user_bm25", new_callable=AsyncMock) as mock_bm25, \
             patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.unlink") as mock_unlink:
            await delete_user_account(mock_db, mock_user)

        # 向量集合：knowledge_10 + memory_10，不用旧命名 resume_*
        colls = [c.args[0] for c in mock_vs.return_value.delete_collection.await_args_list]
        assert "knowledge_10" in colls
        assert "memory_10" in colls
        assert not any(c.startswith("resume_") for c in colls), "不应再删旧命名 resume_{rid} 集合"

        # 逐简历清 Redis 分析缓存 + Embedding 缓存
        mock_inv.assert_has_awaits([call(1), call(2)])
        mock_emb.assert_has_awaits([call(1), call(2)])
        # 清 BM25（该用户全部 scope key）
        mock_bm25.assert_awaited_once_with(10)
        # 删物理文件
        assert mock_unlink.call_count == 2
        # DB 删除用户（FK 级联）
        mock_db.delete.assert_called_once_with(mock_user)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_resumes_still_cleans_collections(self):
        """用户无简历时仍应删向量集合 + 清 BM25（不留孤儿集合）。"""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        mock_user = MagicMock(id=7)

        with patch(
            "services.user_cleanup_service.get_vector_store",
            return_value=MagicMock(delete_collection=AsyncMock()),
        ) as mock_vs, \
             patch("services.user_cleanup_service.invalidate_resume_cache", new_callable=AsyncMock), \
             patch("services.user_cleanup_service.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("services.user_cleanup_service.clear_user_bm25", new_callable=AsyncMock) as mock_bm25:
            await delete_user_account(mock_db, mock_user)

        colls = [c.args[0] for c in mock_vs.return_value.delete_collection.await_args_list]
        assert "knowledge_7" in colls
        assert "memory_7" in colls
        mock_bm25.assert_awaited_once_with(7)


# ═══════════════════════════════════════════════════════════
# orphan_scan：memory_* 集合孤儿检测
# ═══════════════════════════════════════════════════════════


class TestOrphanScanMemory:
    @pytest.mark.asyncio
    async def test_detects_memory_collection_of_missing_user(self):
        """memory_{user_id} 集合对应用户不存在 → 判为孤儿。"""
        from services.resume_cleanup import orphan_scan

        mock_db = AsyncMock()
        mock_result_empty = MagicMock()
        mock_result_empty.all.return_value = []
        mock_result_users = MagicMock()
        mock_result_users.all.return_value = [(1,)]  # 只有 user 1 存在
        mock_db.execute.side_effect = [mock_result_empty, mock_result_empty, mock_result_users]

        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["memory_999", "memory_1"]

        with patch("services.resume_cleanup.AsyncSessionLocal", return_value=asynccontextmanager_mock(mock_db)), \
             patch("services.resume_cleanup.get_chroma_client", return_value=mock_client), \
             patch("os.listdir", return_value=[]):
            orphans = await orphan_scan()

        assert "memory_999" in orphans["chromadb"]
        assert "memory_1" not in orphans["chromadb"]
