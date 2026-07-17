"""
MCP Agentic RAG — StateGraph 组装 + 端到端集成测试。

测试 MCP 版本的 StateGraph 编译和执行流程。
全部 mock LLM 调用和 MCP 客户端调用。
运行: python -m pytest tests/test_mcp_graph.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import AsyncMock, patch

from services.agentic_rag.state import AgenticRAGState
from services.agentic_rag.mcp_graph import (
    create_mcp_agentic_rag_graph,
    output_node,
    _route_after_route,
    _route_after_evaluate,
    DIRECT_ANSWER_NODE,
    MCP_SEARCH_NODE,
    SELF_REFLECTION_NODE,
)


# ── 辅助 ──────────────────────────────────────────────────

def _make_state(question: str = "你好", **overrides) -> AgenticRAGState:
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


# ── 条件边测试 ─────────────────────────────────────────────

class TestMCPRouteAfterRoute:
    """_route_after_route 条件边测试（MCP 版本）。"""

    def test_search_goes_to_mcp_search(self):
        state = _make_state(route_decision="search")
        assert _route_after_route(state) == MCP_SEARCH_NODE

    def test_direct_answer_goes_to_direct(self):
        state = _make_state(route_decision="direct_answer")
        assert _route_after_route(state) == DIRECT_ANSWER_NODE

    def test_default_goes_to_mcp_search(self):
        state = _make_state(route_decision="")
        assert _route_after_route(state) == MCP_SEARCH_NODE


class TestMCPRouteAfterEvaluate:
    """_route_after_evaluate 条件边测试（MCP 版本）。"""

    def test_no_retry_goes_to_output(self):
        state = _make_state(should_retry=False, search_round=1)
        assert _route_after_evaluate(state) == "output"

    def test_retry_within_limit_goes_to_self_reflection(self):
        state = _make_state(should_retry=True, search_round=1)
        assert _route_after_evaluate(state) == SELF_REFLECTION_NODE

    def test_retry_at_limit_goes_to_self_reflection(self):
        state = _make_state(should_retry=True, search_round=2)
        assert _route_after_evaluate(state) == SELF_REFLECTION_NODE

    def test_retry_exceeds_limit_goes_to_output(self):
        state = _make_state(should_retry=True, search_round=3)
        assert _route_after_evaluate(state) == "output"


# ── Graph 编译测试 ─────────────────────────────────────────

class TestMCPGraphCompilation:
    """MCP StateGraph 编译测试。"""

    def test_graph_compiles(self):
        graph = create_mcp_agentic_rag_graph()
        assert graph is not None

    def test_graph_has_invoke(self):
        graph = create_mcp_agentic_rag_graph()
        assert hasattr(graph, "invoke")

    def test_graph_has_ainvoke(self):
        graph = create_mcp_agentic_rag_graph()
        assert hasattr(graph, "ainvoke")

    def test_graph_with_custom_checkpointer(self):
        from langgraph.checkpoint.memory import MemorySaver
        saver = MemorySaver()
        graph = create_mcp_agentic_rag_graph(checkpointer=saver)
        assert graph is not None


# ── 端到端测试 ─────────────────────────────────────────────

class TestMCPGraphEndToEnd:
    """MCP StateGraph 端到端执行测试。"""

    @pytest.mark.asyncio
    async def test_direct_answer_path(self):
        """问候 → route=direct_answer → direct_answer → output → END。"""
        graph = create_mcp_agentic_rag_graph()

        with (
            patch("services.agentic_rag.rewrite.with_retry", new_callable=AsyncMock, return_value="你好"),
            patch("services.agentic_rag.rewrite._classify_route", new_callable=AsyncMock, return_value="direct_answer"),
        ):
            result = await graph.ainvoke({
                "question": "你好",
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
            }, config={"configurable": {"thread_id": "test-mcp-direct"}})

        assert result["route_decision"] == "direct_answer"
        assert result["final_answer"] != ""
        assert "direct_answer" in result["trace"]

    @pytest.mark.asyncio
    async def test_mcp_search_path_single_round(self):
        """search → mcp_search → mcp_rerank → mcp_generate → evaluate(pass) → output。"""
        graph = create_mcp_agentic_rag_graph()

        mock_search_results = [
            {"text": "工作经验", "chunk_index": 0, "section": "工作经历", "score": 0.9},
        ]
        mock_rerank_results = [
            {"text": "工作经验", "chunk_index": 0, "section": "工作经历", "rerank_score": 0.95},
        ]
        mock_generate_result = {
            "answer": "候选人有3年工作经验。",
            "sources": [{"chunk_index": 0, "text": "工作经验", "section": "工作经历", "rerank_score": 0.95}],
            "rejected": False,
        }

        with (
            patch("services.agentic_rag.rewrite.with_retry", new_callable=AsyncMock, return_value="工作经历"),
            patch("services.agentic_rag.rewrite._classify_route", new_callable=AsyncMock, return_value="search"),
            patch("services.agentic_rag.mcp_nodes.mcp_search", new_callable=AsyncMock, return_value=mock_search_results),
            patch("services.agentic_rag.mcp_nodes.mcp_rerank", new_callable=AsyncMock, return_value=mock_rerank_results),
            patch("services.agentic_rag.mcp_nodes.mcp_generate", new_callable=AsyncMock, return_value=mock_generate_result),
            patch("services.agentic_rag.generate.with_retry", new_callable=AsyncMock, return_value='{"completeness": 8, "accuracy": 8, "source_credibility": 8, "feedback": "回答准确"}'),
        ):
            result = await graph.ainvoke({
                "question": "工作经历是什么？",
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
            }, config={"configurable": {"thread_id": "test-mcp-search-pass"}})

        assert result["route_decision"] == "search"
        assert result["search_round"] >= 1
        assert result["final_answer"] == "候选人有3年工作经验。"
        assert len(result["final_sources"]) > 0
        assert result["eval_score"] > 0.6

        # 验证 trace 中标记了 MCP 方法
        assert result["trace"]["search"]["method"] == "mcp"
        assert result["trace"]["generate"]["method"] == "mcp"

    @pytest.mark.asyncio
    async def test_mcp_search_path_with_retry(self):
        """evaluate(低分) → should_retry → mcp_search(第2轮) → evaluate(通过) → output。"""
        graph = create_mcp_agentic_rag_graph()

        mock_search_results = [{"text": "片段", "chunk_index": 0, "section": "工作经历", "score": 0.8}]
        mock_rerank_results = [{"text": "片段", "chunk_index": 0, "section": "工作经历", "rerank_score": 0.9}]
        mock_generate_result = {
            "answer": "答案内容",
            "sources": [{"chunk_index": 0, "text": "片段", "section": "工作经历", "rerank_score": 0.9}],
            "rejected": False,
        }

        with (
            patch("services.agentic_rag.rewrite.with_retry", new_callable=AsyncMock, return_value="查询"),
            patch("services.agentic_rag.rewrite._classify_route", new_callable=AsyncMock, return_value="search"),
            patch("services.agentic_rag.mcp_nodes.mcp_search", new_callable=AsyncMock, return_value=mock_search_results),
            patch("services.agentic_rag.mcp_nodes.mcp_rerank", new_callable=AsyncMock, return_value=mock_rerank_results),
            patch("services.agentic_rag.mcp_nodes.mcp_generate", new_callable=AsyncMock, return_value=mock_generate_result),
            patch("services.agentic_rag.generate.with_retry", new_callable=AsyncMock, side_effect=[
                '{"completeness": 4, "accuracy": 4, "source_credibility": 4, "feedback": "不够详细"}',  # eval round 1 → should_retry
                '{"completeness": 8, "accuracy": 8, "source_credibility": 8, "feedback": "回答准确"}',   # eval round 2 → pass
            ]),
        ):
            result = await graph.ainvoke({
                "question": "工作经历？",
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
            }, config={"configurable": {"thread_id": "test-mcp-retry"}})

        assert result["search_round"] >= 2
        assert result["final_answer"] != ""

    @pytest.mark.asyncio
    async def test_mcp_search_empty_triggers_rejection(self):
        """MCP 搜索返回空结果 → generate 拒答 → evaluate 跳过 → output。"""
        graph = create_mcp_agentic_rag_graph()

        with (
            patch("services.agentic_rag.rewrite.with_retry", new_callable=AsyncMock, return_value="查询"),
            patch("services.agentic_rag.rewrite._classify_route", new_callable=AsyncMock, return_value="search"),
            patch("services.agentic_rag.mcp_nodes.mcp_search", new_callable=AsyncMock, return_value=[]),
            patch("services.agentic_rag.mcp_nodes.mcp_rerank", new_callable=AsyncMock, return_value=[]),
            patch("services.agentic_rag.mcp_nodes.mcp_generate", new_callable=AsyncMock, return_value={
                "answer": "抱歉，简历中未提及该信息。",
                "sources": [],
                "rejected": True,
            }),
        ):
            result = await graph.ainvoke({
                "question": "航天经历？",
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
            }, config={"configurable": {"thread_id": "test-mcp-empty"}})

        assert "未提及" in result["final_answer"]
        assert result["trace"]["generate"]["rejected"] is True


# ── 边界条件 ───────────────────────────────────────────────

class TestMCPEdgeCases:
    """MCP 版本边界条件测试。"""

    def test_route_after_evaluate_retry_at_boundary(self):
        state = _make_state(should_retry=True, search_round=2)
        assert _route_after_evaluate(state) == SELF_REFLECTION_NODE

    def test_route_after_evaluate_retry_over_boundary(self):
        state = _make_state(should_retry=True, search_round=3)
        assert _route_after_evaluate(state) == "output"

    @pytest.mark.asyncio
    async def test_output_preserves_mcp_trace(self):
        """output_node 保留 MCP trace 信息。"""
        state = _make_state(
            answer="答案",
            sources=[],
            trace={
                "rewrite": {"elapsed_ms": 100},
                "search": {"method": "mcp", "elapsed_ms": 200},
                "rerank": {"method": "mcp", "elapsed_ms": 50},
                "generate": {"method": "mcp", "elapsed_ms": 500},
            },
        )
        result = await output_node(state)
        assert result["trace"]["search"]["method"] == "mcp"
        assert result["trace"]["generate"]["method"] == "mcp"
