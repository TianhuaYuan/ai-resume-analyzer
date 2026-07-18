"""
Agentic RAG MCP 节点单元测试。

测试 mcp_search_node、mcp_rerank_node、mcp_generate_node。
全部 mock MCP 客户端调用，不依赖真实 MCP Server。
运行: python -m pytest tests/test_mcp_nodes.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.agentic_rag.state import AgenticRAGState
from services.agentic_rag.mcp_nodes import mcp_search_node, mcp_rerank_node, mcp_generate_node


# ── 辅助 ──────────────────────────────────────────────────

def _make_state(question: str = "工作经历是什么？", **overrides) -> AgenticRAGState:
    """构造最小 AgenticRAGState。"""
    base: AgenticRAGState = {
        "question": question,
        "resume_id": 1,
        "rewritten_query": "",
        "route_decision": "",
        "chunks": [],
        "search_round": 0,
        "answer": "",
        "sources": [],
        "eval_score": 0.0,
        "eval_feedback": "",
        "should_retry": False,
        "final_answer": "",
        "final_sources": [],
        "trace": {},
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


# ── mcp_search_node 测试 ───────────────────────────────────

class TestMCPSearchNode:
    """mcp_search_node 测试。"""

    @pytest.mark.asyncio
    async def test_search_returns_chunks(self):
        """正常搜索返回 chunks。"""
        mock_results = [
            {"text": "工作经验", "score": 0.9, "section": "工作经历", "chunk_index": 0},
            {"text": "项目经历", "score": 0.8, "section": "项目经历", "chunk_index": 1},
        ]

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_search",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            state = _make_state(rewritten_query="工作经历", search_round=0)
            result = await mcp_search_node(state)

            assert len(result["chunks"]) == 2
            assert result["search_round"] == 1
            assert result["trace"]["search"]["method"] == "mcp"

    @pytest.mark.asyncio
    async def test_search_uses_rewritten_query(self):
        """使用 rewritten_query 而非原始 question。"""
        with patch(
            "services.agentic_rag.mcp_nodes.mcp_search",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock:
            state = _make_state(
                question="他的学历是什么",
                rewritten_query="简历中候选人的教育背景",
            )
            await mcp_search_node(state)

            call_args = mock.call_args
            assert call_args[0][0] == "简历中候选人的教育背景"

    @pytest.mark.asyncio
    async def test_search_falls_back_to_question(self):
        """rewritten_query 为空时使用原始 question。"""
        with patch(
            "services.agentic_rag.mcp_nodes.mcp_search",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock:
            state = _make_state(question="工作经历？", rewritten_query="")
            await mcp_search_node(state)

            call_args = mock.call_args
            assert call_args[0][0] == "工作经历？"

    @pytest.mark.asyncio
    async def test_search_increments_round(self):
        """search_round 递增。"""
        with patch(
            "services.agentic_rag.mcp_nodes.mcp_search",
            new_callable=AsyncMock,
            return_value=[],
        ):
            state = _make_state(search_round=1)
            result = await mcp_search_node(state)
            assert result["search_round"] == 2

    @pytest.mark.asyncio
    async def test_search_handles_dict_result(self):
        """处理 dict 类型的 MCP 返回结果。"""
        mock_results = {"results": [{"text": "内容", "score": 0.8}]}

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_search",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            state = _make_state()
            result = await mcp_search_node(state)
            assert len(result["chunks"]) == 1

    @pytest.mark.asyncio
    async def test_search_handles_error(self):
        """处理 MCP 错误返回。"""
        mock_results = {"error": "Resume not found"}

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_search",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            state = _make_state()
            result = await mcp_search_node(state)
            assert result["chunks"] == []


# ── mcp_rerank_node 测试 ───────────────────────────────────

class TestMCPRerankNode:
    """mcp_rerank_node 测试。"""

    @pytest.mark.asyncio
    async def test_rerank_returns_sorted_chunks(self):
        """正常精排返回排序后的 chunks。"""
        mock_results = [
            {"text": "最相关", "rerank_score": 0.95, "section": "工作经历"},
            {"text": "次相关", "rerank_score": 0.7, "section": "项目经历"},
        ]

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_rerank",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            state = _make_state(
                chunks=[
                    {"text": "次相关", "section": "项目经历"},
                    {"text": "最相关", "section": "工作经历"},
                ],
                rewritten_query="工作经历",
            )
            result = await mcp_rerank_node(state)

            assert len(result["chunks"]) == 2
            assert result["chunks"][0]["rerank_score"] >= result["chunks"][1]["rerank_score"]
            assert result["trace"]["rerank"]["method"] == "mcp"

    @pytest.mark.asyncio
    async def test_rerank_empty_chunks(self):
        """空 chunks 直接返回。"""
        state = _make_state(chunks=[], rewritten_query="test")
        result = await mcp_rerank_node(state)
        assert result["chunks"] == []
        assert result["trace"]["rerank"]["input_count"] == 0

    @pytest.mark.asyncio
    async def test_rerank_handles_dict_result(self):
        """处理 dict 类型返回。"""
        mock_results = {"results": [{"text": "内容", "rerank_score": 0.9}]}

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_rerank",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            state = _make_state(chunks=[{"text": "内容"}])
            result = await mcp_rerank_node(state)
            assert len(result["chunks"]) == 1

    @pytest.mark.asyncio
    async def test_rerank_handles_error(self):
        """处理 MCP 错误时降级返回原始顺序。"""
        mock_results = {"error": "Rerank failed"}

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_rerank",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            chunks = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
            state = _make_state(chunks=chunks)
            result = await mcp_rerank_node(state)
            # 降级：保持原始顺序，截断到 top_k
            assert len(result["chunks"]) <= 5


# ── mcp_generate_node 测试 ─────────────────────────────────

class TestMCPGenerateNode:
    """mcp_generate_node 测试。"""

    @pytest.mark.asyncio
    async def test_generate_returns_answer(self):
        """正常生成返回答案和来源。"""
        mock_result = {
            "answer": "候选人有3年工作经验",
            "sources": [{"text": "工作经验", "section": "工作经历", "rerank_score": 0.9}],
            "rejected": False,
        }

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_generate",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            state = _make_state(
                chunks=[{"text": "工作经验", "section": "工作经历", "rerank_score": 0.9}],
                rewritten_query="工作经历",
            )
            result = await mcp_generate_node(state)

            assert result["answer"] == "候选人有3年工作经验"
            assert len(result["sources"]) == 1
            assert result["trace"]["generate"]["rejected"] is False
            assert result["trace"]["generate"]["method"] == "mcp"

    @pytest.mark.asyncio
    async def test_generate_rejects_empty_chunks(self):
        """无 chunks 时拒答。"""
        state = _make_state(chunks=[], rewritten_query="test")
        result = await mcp_generate_node(state)
        assert "未提及" in result["answer"]
        assert result["trace"]["generate"]["rejected"] is True

    @pytest.mark.asyncio
    async def test_generate_rejects_low_rerank_score(self):
        """rerank_score 过低时拒答。"""
        chunks = [{"text": "内容", "rerank_score": 0.1}]
        state = _make_state(chunks=chunks, rewritten_query="test")
        result = await mcp_generate_node(state)
        assert "未提及" in result["answer"]

    @pytest.mark.asyncio
    async def test_generate_handles_mcp_error(self):
        """MCP 错误时返回降级答案。"""
        with patch(
            "services.agentic_rag.mcp_nodes.mcp_generate",
            new_callable=AsyncMock,
            return_value={"error": "Connection failed"},
        ):
            chunks = [{"text": "内容", "rerank_score": 0.9}]
            state = _make_state(chunks=chunks, rewritten_query="test")
            result = await mcp_generate_node(state)
            assert "不可用" in result["answer"]
            assert result["trace"]["generate"]["rejected"] is True

    @pytest.mark.asyncio
    async def test_generate_uses_mcp_sources_when_available(self):
        """优先使用 MCP 返回的 sources。"""
        mcp_sources = [{"text": "MCP来源", "section": "来源"}]
        mock_result = {
            "answer": "答案",
            "sources": mcp_sources,
            "rejected": False,
        }

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_generate",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            chunks = [{"text": "本地来源", "section": "本地", "rerank_score": 0.8}]
            state = _make_state(chunks=chunks, rewritten_query="test")
            result = await mcp_generate_node(state)
            assert result["sources"] == mcp_sources

    @pytest.mark.asyncio
    async def test_generate_falls_back_to_local_sources(self):
        """MCP 未返回 sources 时使用本地 _extract_sources。"""
        mock_result = {"answer": "答案", "rejected": False}

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_generate",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            chunks = [{"text": "来源", "section": "工作经历", "chunk_index": 0, "rerank_score": 0.9}]
            state = _make_state(chunks=chunks, rewritten_query="test")
            result = await mcp_generate_node(state)
            # 使用 _extract_sources 生成的来源
            assert len(result["sources"]) == 1
            assert result["sources"][0]["text"] == "来源"

    @pytest.mark.asyncio
    async def test_generate_handles_dict_result(self):
        """处理 dict 类型返回（包含 answer 字段）。"""
        mock_result = {"answer": "生成的答案", "rejected": False}

        with patch(
            "services.agentic_rag.mcp_nodes.mcp_generate",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            chunks = [{"text": "内容", "rerank_score": 0.9}]
            state = _make_state(chunks=chunks, rewritten_query="test")
            result = await mcp_generate_node(state)
            assert result["answer"] == "生成的答案"
