"""记忆提炼写路径回归（A1：with_retry 修复 fallback bug）。

历史 bug：extraction 直接调 llm_generate(..., fallback="[]") 但 llm_generate 无该参数
→ 每次 TypeError 被吞 → 记忆从未写入。修复后改用 with_retry(llm_generate, ..., fallback="[]")。
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.memory.extraction import _parse_facts, extract_and_save_memories


class TestParseFacts:
    def test_parses_json_array(self):
        assert _parse_facts('["事实A", "事实B"]') == ["事实A", "事实B"]

    def test_parses_empty_array(self):
        assert _parse_facts("[]") == []

    def test_falls_back_to_quoted_strings(self):
        """JSON 解析失败 → 降级抓取引号字符串。"""
        raw = '解析结果：["事实内容"] 和更多'
        parsed = _parse_facts(raw)
        assert "事实内容" in parsed

    def test_returns_empty_on_garbage(self):
        assert _parse_facts("完全不是JSON") == []

    def test_limits_to_max_items(self):
        assert len(_parse_facts('["1", "2", "3", "4", "5"]', max_items=3)) == 3


class TestExtractAndSaveMemories:
    @pytest.mark.asyncio
    async def test_saves_extracted_facts(self):
        """with_retry 返回 JSON 数组 → 逐条 save_memory。"""
        with patch(
            "services.memory.extraction.with_retry",
            new_callable=AsyncMock,
            return_value='["喜欢Go语言", "目标进字节后端"]',
        ), patch(
            "services.memory.extraction.recall_memory",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "services.memory.extraction.save_memory",
            new_callable=AsyncMock,
            return_value="mem-1",
        ) as mock_save:
            saved = await extract_and_save_memories(user_id=1, conversation_text="我喜欢Go")

        assert len(saved) == 2
        assert mock_save.call_count == 2

    @pytest.mark.asyncio
    async def test_fallback_to_empty_on_failure(self):
        """with_retry 重试耗尽返回 "[]" → 无写入、返回空列表（不抛 TypeError）。"""
        with patch(
            "services.memory.extraction.with_retry",
            new_callable=AsyncMock,
            return_value="[]",
        ), patch("services.memory.extraction.save_memory", new_callable=AsyncMock) as mock_save:
            saved = await extract_and_save_memories(user_id=1, conversation_text="你好")

        assert saved == []
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self):
        """with_retry 抛异常 → 外层 try 捕获，返回空列表（不阻塞主流程）。"""
        with patch(
            "services.memory.extraction.with_retry",
            new_callable=AsyncMock,
            side_effect=Exception("LLM down"),
        ), patch("services.memory.extraction.save_memory", new_callable=AsyncMock) as mock_save:
            saved = await extract_and_save_memories(user_id=1, conversation_text="你好")

        assert saved == []
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_skips_duplicate_fact(self):
        """recall_memory 命中相似事实 → 跳过写入（去重）。"""
        with patch(
            "services.memory.extraction.with_retry",
            new_callable=AsyncMock,
            return_value='["重复事实"]',
        ), patch(
            "services.memory.extraction.recall_memory",
            new_callable=AsyncMock,
            return_value=[{"memory_id": "existing", "text": "重复事实", "score": 0.9}],
        ), patch("services.memory.extraction.save_memory", new_callable=AsyncMock) as mock_save:
            saved = await extract_and_save_memories(user_id=1, conversation_text="重复")

        assert saved == []
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_with_retry_not_direct_llm_generate(self):
        """断言走 with_retry（而非直接 llm_generate），且 fallback 传给 with_retry。"""
        with patch(
            "services.memory.extraction.with_retry",
            new_callable=AsyncMock,
            return_value="[]",
        ) as mock_retry, patch("services.memory.extraction.recall_memory", new_callable=AsyncMock), patch(
            "services.memory.extraction.save_memory", new_callable=AsyncMock
        ):
            await extract_and_save_memories(user_id=1, conversation_text="你好")

        mock_retry.assert_awaited_once()
        kwargs = mock_retry.await_args.kwargs
        assert kwargs.get("fallback") == "[]"
        assert kwargs.get("user_id") == 1
