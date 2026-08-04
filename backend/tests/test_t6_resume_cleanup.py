"""T6: resume_cleanup 级联删除 + 孤儿扫描 + stale processing 清扫。

测试范围：
- delete_resume_full: DB 先删，外部尽力清理
- cleanup_stale_processing: >30min 的 processing resume 标记 failed
- orphan_scan: 扫描磁盘孤儿文件、Chroma 孤儿 collection
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select


# ═══════════════════════════════════════════════════════════
# RED: delete_resume_full
# ═══════════════════════════════════════════════════════════


class TestDeleteResumeFull:
    """delete_resume_full: DB 事务先行 → 外部尽力清理 → 日志。"""

    @pytest.mark.asyncio
    async def test_deletes_db_first(self):
        """DB 记录应先被删除。"""
        from services.resume_cleanup import delete_resume_full

        mock_db = AsyncMock()
        mock_resume = MagicMock()
        mock_resume.id = 1
        mock_resume.user_id = 100
        mock_resume.file_path = "/uploads/abc.pdf"

        with patch("services.resume_cleanup.clear_resume_vectors") as mock_clear, \
             patch("services.resume_cleanup.embedding_cache.clear_resume", new_callable=AsyncMock) as mock_emb, \
             patch("os.path.exists", return_value=True), \
             patch("os.remove") as mock_remove:

            await delete_resume_full(mock_db, mock_resume)

        # DB 删除应先执行
        mock_db.delete.assert_called_once_with(mock_resume)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_clears_external_resources(self):
        """DB 删除后应尽力清理外部资源。"""
        from services.resume_cleanup import delete_resume_full

        mock_db = AsyncMock()
        mock_resume = MagicMock()
        mock_resume.id = 1
        mock_resume.user_id = 100
        mock_resume.file_path = "/uploads/abc.pdf"

        with patch("services.resume_cleanup.clear_resume_vectors") as mock_clear, \
             patch("services.resume_cleanup.embedding_cache.clear_resume", new_callable=AsyncMock) as mock_emb, \
             patch("os.path.exists", return_value=True), \
             patch("os.remove") as mock_remove:

            await delete_resume_full(mock_db, mock_resume)

        mock_clear.assert_called_once_with(100, 1)
        mock_emb.assert_called_once_with(1)
        mock_remove.assert_called_once_with("/uploads/abc.pdf")

    @pytest.mark.asyncio
    async def test_logs_on_external_failure(self):
        """外部资源清理失败不应抛异常，应记录日志。"""
        from services.resume_cleanup import delete_resume_full

        mock_db = AsyncMock()
        mock_resume = MagicMock()
        mock_resume.id = 1
        mock_resume.user_id = 100
        mock_resume.file_path = "/uploads/abc.pdf"

        with patch("services.resume_cleanup.clear_resume_vectors", side_effect=Exception("chroma fail")), \
             patch("services.resume_cleanup.embedding_cache.clear_resume", side_effect=Exception("cache fail")), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove", side_effect=Exception("disk fail")), \
             patch("services.resume_cleanup.logger") as mock_logger:

            # 不应抛异常
            await delete_resume_full(mock_db, mock_resume)

        # DB 仍应被删除
        mock_db.delete.assert_called_once()
        mock_db.commit.assert_called_once()
        # 错误应被记录
        assert mock_logger.warning.call_count >= 1

    @pytest.mark.asyncio
    async def test_skips_file_if_not_exists(self):
        """文件不存在时不调用 os.remove。"""
        from services.resume_cleanup import delete_resume_full

        mock_db = AsyncMock()
        mock_resume = MagicMock()
        mock_resume.id = 1
        mock_resume.file_path = "/uploads/missing.pdf"

        with patch("services.resume_cleanup.clear_resume_vectors"), \
             patch("services.resume_cleanup.embedding_cache.clear_resume", new_callable=AsyncMock), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove") as mock_remove:

            await delete_resume_full(mock_db, mock_resume)

        mock_remove.assert_not_called()


# ═══════════════════════════════════════════════════════════
# RED: cleanup_stale_processing
# ═══════════════════════════════════════════════════════════


class TestCleanupStaleProcessing:
    """cleanup_stale_processing: 清扫超过 30min 的 processing 简历。"""

    @pytest.mark.asyncio
    async def test_marks_stale_as_failed(self):
        """创建时间超过 30min 的 processing 简历应被标记为 failed。"""
        from services.resume_cleanup import cleanup_stale_processing

        stale_time = datetime.now(timezone.utc) - timedelta(minutes=31)
        stale_resume = MagicMock()
        stale_resume.id = 1
        stale_resume.status = "processing"
        stale_resume.created_at = stale_time

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stale_resume]

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        with patch("services.resume_cleanup.AsyncSessionLocal", return_value=asynccontextmanager_mock(mock_db)):
            count = await cleanup_stale_processing()

        assert count == 1
        assert stale_resume.status == "failed"
        assert "处理超时" in stale_resume.status_message
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_recent_processing(self):
        """创建时间 <30min 的 processing 简历不应被清扫。"""
        from services.resume_cleanup import cleanup_stale_processing

        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_resume = MagicMock()
        recent_resume.id = 1
        recent_resume.status = "processing"
        recent_resume.created_at = recent_time

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        with patch("services.resume_cleanup.AsyncSessionLocal", return_value=asynccontextmanager_mock(mock_db)):
            count = await cleanup_stale_processing()

        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_non_processing(self):
        """非 processing 状态的简历不应被清扫。"""
        from services.resume_cleanup import cleanup_stale_processing

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        with patch("services.resume_cleanup.AsyncSessionLocal", return_value=asynccontextmanager_mock(mock_db)):
            count = await cleanup_stale_processing()

        assert count == 0


# ═══════════════════════════════════════════════════════════
# RED: orphan_scan
# ═══════════════════════════════════════════════════════════


class TestOrphanScan:
    """orphan_scan: 扫描没有 DB 记录的孤儿文件和 Chroma collection。"""

    @pytest.mark.asyncio
    async def test_finds_orphan_files(self):
        """磁盘上有但 DB 中没有对应 resume 的文件应被识别为孤儿。"""
        from services.resume_cleanup import orphan_scan

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # DB 中没有 resume
        mock_db.execute.return_value = mock_result

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.__truediv__ = lambda self, x: Path("/uploads") / x
        mock_path.__truediv__ = lambda self, x: MagicMock(is_file=MagicMock(return_value=True))

        with patch("services.resume_cleanup.AsyncSessionLocal", return_value=asynccontextmanager_mock(mock_db)), \
             patch("os.listdir", return_value=["abc-123.pdf", "def-456.docx"]), \
             patch("services.resume_cleanup.UPLOAD_DIR", mock_path):

            orphans = await orphan_scan()

        assert len(orphans["files"]) == 2
        assert "abc-123.pdf" in orphans["files"]

    @pytest.mark.asyncio
    async def test_skips_files_with_db_record(self):
        """DB 中有对应 resume 的文件不应被识别为孤儿。"""
        from services.resume_cleanup import orphan_scan

        mock_db = AsyncMock()

        # 第一次 execute: select(Resume.file_path) → 返回 Row 元组
        mock_result_paths = MagicMock()
        mock_result_paths.all.return_value = [("/uploads/existing.pdf",)]

        # 第二次 execute: select(Resume.id) → 返回 Row 元组
        mock_result_ids = MagicMock()
        mock_result_ids.all.return_value = [(1,)]

        # 第三次 execute: select(User.id) → 返回用户 id 元组
        mock_result_users = MagicMock()
        mock_result_users.all.return_value = [(1,)]

        mock_db.execute.side_effect = [mock_result_paths, mock_result_ids, mock_result_users]

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.__truediv__ = lambda self, x: MagicMock(is_file=MagicMock(return_value=True))

        with patch("services.resume_cleanup.AsyncSessionLocal", return_value=asynccontextmanager_mock(mock_db)), \
             patch("os.listdir", return_value=["existing.pdf", "orphan.pdf"]), \
             patch("services.resume_cleanup.UPLOAD_DIR", mock_path):

            orphans = await orphan_scan()

        assert "existing.pdf" not in orphans["files"]
        assert "orphan.pdf" in orphans["files"]

    @pytest.mark.asyncio
    async def test_finds_orphan_chroma_collections(self):
        """Chroma 中有但 DB 中没有对应的 collection 应被识别为孤儿。"""
        from services.resume_cleanup import orphan_scan

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["resume_1", "resume_2"]

        with patch("services.resume_cleanup.AsyncSessionLocal", return_value=asynccontextmanager_mock(mock_db)), \
             patch("services.resume_cleanup.get_chroma_client", return_value=mock_client), \
             patch("os.listdir", return_value=[]):

            orphans = await orphan_scan()

        assert "resume_1" in orphans["chromadb"]
        assert "resume_2" in orphans["chromadb"]

    @pytest.mark.asyncio
    async def test_knowledge_orphan_when_user_missing(self):
        """knowledge_{user_id} 集合：对应用户不存在 → 判为孤儿。"""
        from services.resume_cleanup import orphan_scan

        mock_db = AsyncMock()
        mock_result_empty = MagicMock()
        mock_result_empty.all.return_value = []  # file_path + Resume.id 均空
        mock_result_users = MagicMock()
        mock_result_users.all.return_value = [(2,)]  # 只有 user 2 存在
        mock_db.execute.side_effect = [mock_result_empty, mock_result_empty, mock_result_users]

        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["knowledge_999"]

        with patch("services.resume_cleanup.AsyncSessionLocal", return_value=asynccontextmanager_mock(mock_db)), \
             patch("services.resume_cleanup.get_chroma_client", return_value=mock_client), \
             patch("os.listdir", return_value=[]):

            orphans = await orphan_scan()

        assert "knowledge_999" in orphans["chromadb"]

    @pytest.mark.asyncio
    async def test_knowledge_collection_not_orphan_when_user_exists(self):
        """knowledge_{user_id} 集合：对应用户存在 → 不判为孤儿。"""
        from services.resume_cleanup import orphan_scan

        mock_db = AsyncMock()
        mock_result_empty = MagicMock()
        mock_result_empty.all.return_value = []
        mock_result_users = MagicMock()
        mock_result_users.all.return_value = [(1,)]
        mock_db.execute.side_effect = [mock_result_empty, mock_result_empty, mock_result_users]

        mock_client = MagicMock()
        mock_client.list_collections.return_value = ["knowledge_1"]

        with patch("services.resume_cleanup.AsyncSessionLocal", return_value=asynccontextmanager_mock(mock_db)), \
             patch("services.resume_cleanup.get_chroma_client", return_value=mock_client), \
             patch("os.listdir", return_value=[]):

            orphans = await orphan_scan()

        assert "knowledge_1" not in orphans["chromadb"]


# ═══════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════

def asynccontextmanager_mock(mock_db):
    """创建一个异步上下文管理器 mock，用于 AsyncSessionLocal。"""
    class _MockSession:
        async def __aenter__(self):
            return mock_db
        async def __aexit__(self, *args):
            pass
    return _MockSession()
