"""
Agentic RAG — StateGraph 组装 + 节点集成测试。

全部 mock LLM 调用和外部依赖，不依赖数据库/API。
运行: python -m pytest tests/test_agentic_graph.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.agentic_rag.state import AgenticRAGState
from services.agentic_rag.graph import (
    create_agentic_rag_graph,
    direct_answer_node,
    output_node,
    _route_after_route_standard as _route_after_route,
    _route_after_evaluate,
    DIRECT_ANSWER_NODE,
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
        "completeness_score": 0.0,
        "accuracy_score": 0.0,
        "source_credibility_score": 0.0,
        "reflection_result": "",
        "missing_info": [],
        "supplement_queries": [],
        "reflection_round": 0,
        "final_answer": "",
        "final_sources": [],
        "trace": {},
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


# ── 条件边函数测试 ─────────────────────────────────────────


class TestRouteAfterRoute:
    """_route_after_route 条件边测试。"""

    def test_search_decision(self):
        state = _make_state(route_decision="search")
        assert _route_after_route(state) == "search"

    def test_direct_answer_decision(self):
        state = _make_state(route_decision="direct_answer")
        assert _route_after_route(state) == DIRECT_ANSWER_NODE

    def test_default_is_search(self):
        state = _make_state(route_decision="")
        assert _route_after_route(state) == "search"

    def test_unknown_defaults_to_search(self):
        state = _make_state(route_decision="unknown_value")
        assert _route_after_route(state) == "search"


class TestRouteAfterEvaluate:
    """_route_after_evaluate 条件边测试（Reflexion版本）。"""

    def test_no_retry_goes_to_output(self):
        state = _make_state(should_retry=False, search_round=1)
        assert _route_after_evaluate(state) == "output"

    def test_retry_within_limit_goes_to_self_reflection(self):
        """should_retry=True 且 round=1 → 进入 self_reflection（第1轮反思）。"""
        state = _make_state(should_retry=True, search_round=1)
        assert _route_after_evaluate(state) == "self_reflection"

    def test_retry_at_limit_2_goes_to_self_reflection(self):
        """P0.3 修复：round=2 时仍允许进入第2轮 Reflexion 反思。

        修复前：< 比较 → 2 < 2 = False → 直接 output，实际只跑1轮反思。
        修复后：<= 比较 → 2 <= 2 = True → 进入第2轮反思，确保真正的 ≤2 轮 Reflexion。
        第3轮搜索后 search_round=3，evaluate_node 中 `search_round > _EVAL_MAX_RETRIES`
        会强制 should_retry=False，从而在 _route_after_evaluate 走 output。
        """
        state = _make_state(should_retry=True, search_round=2)
        assert _route_after_evaluate(state) == "self_reflection"

    def test_retry_exceeds_limit_goes_to_output(self):
        """round=3 时即使 should_retry=True 也输出（由 evaluate_node 强制 should_retry=False 兜底）。"""
        state = _make_state(should_retry=True, search_round=3)
        assert _route_after_evaluate(state) == "output"

    def test_default_no_retry(self):
        state = _make_state()
        assert _route_after_evaluate(state) == "output"


# ── Direct Answer Node 测试 ────────────────────────────────


class TestDirectAnswerNode:
    """direct_answer_node 测试。"""

    @pytest.mark.asyncio
    async def test_returns_template_reply(self):
        state = _make_state(question="你好")
        result = await direct_answer_node(state)
        assert "你好" in result["answer"] or "简历" in result["answer"]
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_trace_recorded(self):
        state = _make_state()
        result = await direct_answer_node(state)
        assert "direct_answer" in result["trace"]


# ── Output Node 测试 ───────────────────────────────────────


class TestOutputNode:
    """output_node 测试。"""

    @pytest.mark.asyncio
    async def test_copies_answer_to_final(self):
        state = _make_state(
            answer="这是答案",
            sources=[{"text": "片段1", "section": "工作经历"}],
        )
        result = await output_node(state)
        assert result["final_answer"] == "这是答案"
        assert len(result["final_sources"]) == 1

    @pytest.mark.asyncio
    async def test_sources_serialized_as_json(self):
        import json

        source = {"text": "片段", "section": "教育背景", "rerank_score": 0.9}
        state = _make_state(answer="答", sources=[source])
        result = await output_node(state)
        parsed = json.loads(result["final_sources"][0])
        assert parsed["text"] == "片段"
        assert parsed["section"] == "教育背景"

    @pytest.mark.asyncio
    async def test_empty_sources(self):
        state = _make_state(answer="答", sources=[])
        result = await output_node(state)
        assert result["final_sources"] == []

    @pytest.mark.asyncio
    async def test_trace_records_metadata(self):
        state = _make_state(
            answer="答案内容",
            sources=[{"text": "a"}, {"text": "b"}],
            search_round=2,
            eval_score=0.85,
        )
        result = await output_node(state)
        trace = result["trace"]["output"]
        assert trace["answer_length"] == len("答案内容")
        assert trace["source_count"] == 2
        assert trace["search_rounds"] == 2
        assert trace["eval_score"] == 0.85


# ── Graph 编译测试 ─────────────────────────────────────────


class TestGraphCompilation:
    """StateGraph 编译测试。"""

    def test_graph_compiles(self):
        graph = create_agentic_rag_graph()
        assert graph is not None

    def test_graph_has_invoke(self):
        graph = create_agentic_rag_graph()
        assert hasattr(graph, "invoke")

    def test_graph_has_ainvoke(self):
        graph = create_agentic_rag_graph()
        assert hasattr(graph, "ainvoke")

    def test_graph_with_custom_checkpointer(self):
        from langgraph.checkpoint.memory import MemorySaver

        saver = MemorySaver()
        graph = create_agentic_rag_graph(checkpointer=saver)
        assert graph is not None


# ── Graph 端到端测试（mock 所有 LLM/外部调用）──────────────


class TestGraphEndToEnd:
    """StateGraph 端到端执行测试，mock 所有外部依赖。"""

    @pytest.mark.asyncio
    async def test_direct_answer_path(self):
        """问候 → route=direct_answer → direct_answer → output → END。"""
        graph = create_agentic_rag_graph()

        # mock rewrite 返回原问题，route 返回 direct_answer
        with (
            patch(
                "services.agentic_rag.rewrite.with_retry",
                new_callable=AsyncMock,
                return_value="你好",
            ),
            patch(
                "services.agentic_rag.rewrite._classify_route",
                new_callable=AsyncMock,
                return_value="direct_answer",
            ),
        ):
            result = await graph.ainvoke(
                {
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
                },
                config={"configurable": {"thread_id": "test-direct"}},
            )

        assert result["route_decision"] == "direct_answer"
        assert result["final_answer"] != ""
        assert "direct_answer" in result["trace"]

    @pytest.mark.asyncio
    async def test_search_path_single_round(self):
        """search → rerank → generate → evaluate(pass) → output → END。"""
        graph = create_agentic_rag_graph()

        mock_chunks = [{"text": "工作经验", "chunk_index": 0, "section": "工作经历", "score": 0.9}]
        mock_reranked = [
            {"text": "工作经验", "chunk_index": 0, "section": "工作经历", "rerank_score": 0.95}
        ]
        mock_answer = "候选人有3年工作经验。"

        with (
            patch(
                "services.agentic_rag.rewrite.with_retry",
                new_callable=AsyncMock,
                return_value="工作经历",
            ),
            patch(
                "services.agentic_rag.rewrite._classify_route",
                new_callable=AsyncMock,
                return_value="search",
            ),
            patch(
                "services.agentic_rag.search.hybrid_search",
                new_callable=AsyncMock,
                return_value=mock_chunks,
            ),
            patch(
                "services.agentic_rag.search.rerank",
                new_callable=AsyncMock,
                return_value=mock_reranked,
            ),
            patch(
                "services.agentic_rag.generate.build_prompt",
                return_value={"system": "sys", "user": "usr"},
            ),
            patch("services.agentic_rag.generate.reject_if_low_score", return_value=False),
            patch(
                "services.agentic_rag.generate.llm_generate",
                new_callable=AsyncMock,
                return_value=mock_answer,
            ),
            patch(
                "services.agentic_rag.generate.with_retry",
                new_callable=AsyncMock,
                side_effect=[
                    mock_answer,  # generate_node 的 with_retry
                    '{"completeness": 8, "accuracy": 9, "source_credibility": 7, "feedback": "回答准确"}',  # evaluate_node 的 with_retry
                ],
            ),
        ):
            result = await graph.ainvoke(
                {
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
                    "completeness_score": 0.0,
                    "accuracy_score": 0.0,
                    "source_credibility_score": 0.0,
                    "reflection_result": "",
                    "missing_info": [],
                    "supplement_queries": [],
                    "reflection_round": 0,
                    "final_answer": "",
                    "final_sources": [],
                    "trace": {},
                },
                config={"configurable": {"thread_id": "test-search-pass"}},
            )

        assert result["route_decision"] == "search"
        assert result["search_round"] >= 1
        assert result["final_answer"] == mock_answer
        assert len(result["final_sources"]) > 0
        assert result["eval_score"] > 0.6  # 通过阈值

    @pytest.mark.asyncio
    async def test_search_path_with_reflexion(self):
        """evaluate(低分) → self_reflection → search(第2轮) → evaluate(通过) → output。"""
        graph = create_agentic_rag_graph()

        mock_chunks = [{"text": "片段", "chunk_index": 0, "section": "工作经历", "score": 0.8}]
        mock_reranked = [
            {"text": "片段", "chunk_index": 0, "section": "工作经历", "rerank_score": 0.9}
        ]
        mock_answer = "答案内容"
        mock_reflection = '{"reflection": "缺少项目经验", "missing_info": ["项目经历"], "supplement_queries": ["项目开发经验"]}'

        # with_retry 调用序列：rewrite, generate, eval(低分), reflection, generate(第2轮), eval(高分)
        with (
            patch(
                "services.agentic_rag.rewrite.with_retry",
                new_callable=AsyncMock,
                return_value="查询",
            ),
            patch(
                "services.agentic_rag.rewrite._classify_route",
                new_callable=AsyncMock,
                return_value="search",
            ),
            patch(
                "services.agentic_rag.search.hybrid_search",
                new_callable=AsyncMock,
                return_value=mock_chunks,
            ),
            patch(
                "services.agentic_rag.search.rerank",
                new_callable=AsyncMock,
                return_value=mock_reranked,
            ),
            patch(
                "services.agentic_rag.generate.build_prompt",
                return_value={"system": "sys", "user": "usr"},
            ),
            patch("services.agentic_rag.generate.reject_if_low_score", return_value=False),
            patch(
                "services.agentic_rag.generate.llm_generate",
                new_callable=AsyncMock,
                return_value=mock_answer,
            ),
            patch(
                "services.agentic_rag.generate.with_retry",
                new_callable=AsyncMock,
                side_effect=[
                    mock_answer,  # generate round 1
                    '{"completeness": 4, "accuracy": 5, "source_credibility": 3, "feedback": "不够详细"}',  # eval round 1 → should_retry
                    mock_reflection,  # reflection
                    mock_answer,  # generate round 2
                    '{"completeness": 8, "accuracy": 8, "source_credibility": 7, "feedback": "回答准确"}',  # eval round 2 → pass
                ],
            ),
        ):
            result = await graph.ainvoke(
                {
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
                    "completeness_score": 0.0,
                    "accuracy_score": 0.0,
                    "source_credibility_score": 0.0,
                    "reflection_result": "",
                    "missing_info": [],
                    "supplement_queries": [],
                    "reflection_round": 0,
                    "final_answer": "",
                    "final_sources": [],
                    "trace": {},
                },
                config={"configurable": {"thread_id": "test-reflexion"}},
            )

        assert result["search_round"] >= 2
        assert result["reflection_round"] >= 1
        assert result["final_answer"] != ""

    @pytest.mark.asyncio
    async def test_checkpoint_persistence(self):
        """验证 Checkpoint 持久化：同一 thread_id 的两次调用共享状态。"""
        graph = create_agentic_rag_graph()

        thread_id = "test-checkpoint-persist"

        with (
            patch(
                "services.agentic_rag.rewrite.with_retry",
                new_callable=AsyncMock,
                return_value="你好",
            ),
            patch(
                "services.agentic_rag.rewrite._classify_route",
                new_callable=AsyncMock,
                return_value="direct_answer",
            ),
        ):
            # 第一次调用
            result1 = await graph.ainvoke(
                {
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
                },
                config={"configurable": {"thread_id": thread_id}},
            )

        assert result1["final_answer"] != ""

        # 验证 checkpoint 存在（通过 get_state 检查）
        state_snapshot = graph.get_state(config={"configurable": {"thread_id": thread_id}})
        assert state_snapshot is not None
        assert state_snapshot.values.get("final_answer") != ""


# ── 边界条件测试 ───────────────────────────────────────────


class TestEdgeCases:
    """边界条件测试。"""

    def test_route_after_evaluate_retry_at_boundary(self):
        """P0.3 修复：round=2, should_retry=True → 进入第2轮 Reflexion（而非直接 output）。"""
        state = _make_state(should_retry=True, search_round=2)
        assert _route_after_evaluate(state) == "self_reflection"

    def test_route_after_evaluate_retry_over_boundary(self):
        """round=3, should_retry=True → 输出（由 evaluate_node 强制 should_retry=False 兜底）。"""
        state = _make_state(should_retry=True, search_round=3)
        assert _route_after_evaluate(state) == "output"

    @pytest.mark.asyncio
    async def test_output_node_preserves_trace(self):
        """output_node 保留已有 trace 并追加 output 段。"""
        state = _make_state(
            answer="答案",
            sources=[],
            trace={"rewrite": {"elapsed_ms": 100}, "search": {"elapsed_ms": 200}},
        )
        result = await output_node(state)
        assert "rewrite" in result["trace"]
        assert "search" in result["trace"]
        assert "output" in result["trace"]

    @pytest.mark.asyncio
    async def test_direct_answer_preserves_trace(self):
        """direct_answer_node 保留已有 trace。"""
        state = _make_state(trace={"rewrite": {"elapsed_ms": 50}})
        result = await direct_answer_node(state)
        assert "rewrite" in result["trace"]
        assert "direct_answer" in result["trace"]
