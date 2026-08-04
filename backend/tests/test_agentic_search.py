"""
Agentic RAG search/rerank 节点单元测试 — 覆盖节点逻辑，mock 外部依赖。

运行: python -m pytest tests/test_agentic_search.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.agentic_rag.search import search_node, rerank_node


# ── 测试数据 ──────────────────────────────────────────────

SAMPLE_CHUNKS = [
    {
        "text": "精通 Python",
        "score": 0.9,
        "chunk_index": 0,
        "section": "专业技能",
        "source": "dense",
    },
    {
        "text": "3年 FastAPI 经验",
        "score": 0.7,
        "chunk_index": 1,
        "section": "工作经历",
        "source": "sparse",
    },
    {
        "text": "清华大学本科",
        "score": 0.5,
        "chunk_index": 2,
        "section": "教育背景",
        "source": "dense",
    },
]


def _make_state(**overrides):
    """构建测试用 AgenticRAGState。"""
    state = {
        "question": "候选人有哪些技术栈",
        "resume_id": 1,
        "user_id": 1,
        "rewritten_query": "候选人的专业技能和技术栈",
        "route_decision": "search",
        "chunks": [],
        "search_round": 0,
        "trace": {},
    }
    state.update(overrides)
    return state


# ── Search Node ──────────────────────────────────────────


class TestSearchNode:
    @pytest.mark.asyncio
    async def test_returns_chunks_and_increments_round(self):
        """search_node 应返回 chunks 并递增 search_round"""
        state = _make_state()
        with patch("services.agentic_rag.search.hybrid_search_corpus", new_callable=AsyncMock) as mock:
            mock.return_value = SAMPLE_CHUNKS
            result = await search_node(state)

        assert result["chunks"] == SAMPLE_CHUNKS
        assert result["search_round"] == 1
        # search_node 调 hybrid_search_corpus(user_id, scope, query, top_k)
        mock.assert_called_once_with(1, {"resume": [1]}, "候选人的专业技能和技术栈", top_k=20)

    @pytest.mark.asyncio
    async def test_increments_from_existing_round(self):
        """search_round 从已有值递增，不是重置"""
        state = _make_state(search_round=2)
        with patch("services.agentic_rag.search.hybrid_search_corpus", new_callable=AsyncMock) as mock:
            mock.return_value = SAMPLE_CHUNKS
            result = await search_node(state)

        assert result["search_round"] == 3

    @pytest.mark.asyncio
    async def test_trace_contains_search_info(self):
        """trace 应包含 search 节点的耗时和元数据"""
        state = _make_state()
        with patch("services.agentic_rag.search.hybrid_search_corpus", new_callable=AsyncMock) as mock:
            mock.return_value = SAMPLE_CHUNKS
            result = await search_node(state)

        trace = result["trace"]
        assert "search" in trace
        assert "elapsed_ms" in trace["search"]
        assert trace["search"]["query"] == "候选人的专业技能和技术栈"
        assert trace["search"]["chunk_count"] == 3
        assert trace["search"]["round"] == 0

    @pytest.mark.asyncio
    async def test_preserves_existing_trace(self):
        """应保留 state 中已有的 trace 数据"""
        state = _make_state(trace={"rewrite": {"elapsed_ms": 100}})
        with patch("services.agentic_rag.search.hybrid_search_corpus", new_callable=AsyncMock) as mock:
            mock.return_value = SAMPLE_CHUNKS
            result = await search_node(state)

        assert "rewrite" in result["trace"]
        assert "search" in result["trace"]

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """检索无结果时应返回空列表"""
        state = _make_state()
        with patch("services.agentic_rag.search.hybrid_search_corpus", new_callable=AsyncMock) as mock:
            mock.return_value = []
            result = await search_node(state)

        assert result["chunks"] == []
        assert result["trace"]["search"]["chunk_count"] == 0


# ── Rerank Node ──────────────────────────────────────────


class TestRerankNode:
    @pytest.mark.asyncio
    async def test_returns_reranked_chunks(self):
        """rerank_node 应返回精排后的 chunks"""
        reranked = [SAMPLE_CHUNKS[1], SAMPLE_CHUNKS[0]]  # 假设 rerank 改变了顺序
        for c in reranked:
            c["rerank_score"] = 0.8

        state = _make_state(chunks=SAMPLE_CHUNKS)
        with patch("services.agentic_rag.search.rerank", new_callable=AsyncMock) as mock:
            mock.return_value = reranked
            result = await rerank_node(state)

        assert result["chunks"] == reranked
        assert result["chunks"][0]["rerank_score"] == 0.8
        mock.assert_called_once_with("候选人的专业技能和技术栈", SAMPLE_CHUNKS, top_k=5)

    @pytest.mark.asyncio
    async def test_empty_chunks_short_circuit(self):
        """chunks 为空时应直接返回，不调用 rerank"""
        state = _make_state(chunks=[])
        with patch("services.agentic_rag.search.rerank", new_callable=AsyncMock) as mock:
            result = await rerank_node(state)

        assert result["chunks"] == []
        mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_trace_contains_rerank_info(self):
        """trace 应包含 rerank 节点的耗时和元数据"""
        state = _make_state(chunks=SAMPLE_CHUNKS)
        with patch("services.agentic_rag.search.rerank", new_callable=AsyncMock) as mock:
            mock.return_value = SAMPLE_CHUNKS[:2]
            result = await rerank_node(state)

        trace = result["trace"]
        assert "rerank" in trace
        assert "elapsed_ms" in trace["rerank"]
        assert trace["rerank"]["input_count"] == 3
        assert trace["rerank"]["output_count"] == 2

    @pytest.mark.asyncio
    async def test_preserves_existing_trace(self):
        """应保留 state 中已有的 trace 数据"""
        state = _make_state(
            chunks=SAMPLE_CHUNKS,
            trace={"rewrite": {"elapsed_ms": 100}, "search": {"elapsed_ms": 200}},
        )
        with patch("services.agentic_rag.search.rerank", new_callable=AsyncMock) as mock:
            mock.return_value = SAMPLE_CHUNKS
            result = await rerank_node(state)

        assert "rewrite" in result["trace"]
        assert "search" in result["trace"]
        assert "rerank" in result["trace"]


# ── Search + Rerank 联动 ─────────────────────────────────


class TestSearchRerankPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_state_flow(self):
        """search_node → rerank_node 全流程状态应正确流转"""
        reranked_chunks = [
            {**SAMPLE_CHUNKS[0], "rerank_score": 0.95},
            {**SAMPLE_CHUNKS[1], "rerank_score": 0.80},
        ]

        with (
            patch(
                "services.agentic_rag.search.hybrid_search_corpus", new_callable=AsyncMock
            ) as mock_search,
            patch("services.agentic_rag.search.rerank", new_callable=AsyncMock) as mock_rerank,
        ):
            mock_search.return_value = SAMPLE_CHUNKS
            mock_rerank.return_value = reranked_chunks

            # Step 1: search
            state = _make_state()
            search_result = await search_node(state)
            state.update(search_result)

            assert len(state["chunks"]) == 3
            assert state["search_round"] == 1

            # Step 2: rerank
            rerank_result = await rerank_node(state)
            state.update(rerank_result)

            assert len(state["chunks"]) == 2
            assert state["chunks"][0]["rerank_score"] == 0.95
            assert "search" in state["trace"]
            assert "rerank" in state["trace"]
