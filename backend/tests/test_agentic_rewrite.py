"""
Agentic RAG — rewrite_node + route_node 单元测试。

全部 mock LLM 调用，不依赖外部 API。
运行: python -m pytest tests/test_agentic_rewrite.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch

from core.config import settings
from services.agentic_rag.rewrite import (
    rewrite_node,
    route_node,
    _is_trivial_greeting,
    _classify_route,
)
from services.agentic_rag.state import AgenticRAGState


# ── 辅助 ──────────────────────────────────────────────────


def _make_state(question: str, **overrides) -> AgenticRAGState:
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


# ── _is_trivial_greeting ─────────────────────────────────


class TestIsTrivialGreeting:
    """关键词匹配 — 纯逻辑，无 LLM。"""

    @pytest.mark.parametrize(
        "query",
        [
            "你好",
            "您好",
            "hi",
            "Hello",
            "HI",
            "hey",
            "早上好",
            "下午好",
            "晚上好",
            "谢谢",
            "拜拜",
            "再见",
            "bye",
            "在吗",
            "你是谁",
        ],
    )
    def test_greetings_detected(self, query: str):
        assert _is_trivial_greeting(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "这个人的教育背景是什么",  # 正常问题
            "你好，请问他的工作经历有哪些",  # 问候+实质问题
            "帮我分析一下简历",  # 实质请求
            "",  # 空字符串
            "   ",  # 纯空格
        ],
    )
    def test_non_greetings_pass(self, query: str):
        assert _is_trivial_greeting(query) is False


# ── rewrite_node ─────────────────────────────────────────


class TestRewriteNode:
    """rewrite_node — mock LLM 调用。"""

    @pytest.mark.asyncio
    async def test_rewrites_question(self):
        """正常改写：LLM 返回改写结果。"""
        state = _make_state("他有什么技能？")
        with patch(
            "services.agentic_rag.rewrite.rewrite_query",
            new_callable=AsyncMock,
            return_value="该候选人的专业技能有哪些",
        ) as mock_llm:
            result = await rewrite_node(state)

        assert result["rewritten_query"] == "该候选人的专业技能有哪些"
        assert "rewrite" in result["trace"]
        assert result["trace"]["rewrite"]["original"] == "他有什么技能？"
        mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_returns_empty_falls_back_to_original(self):
        """LLM 返回空字符串 → 兜底原问题。"""
        state = _make_state("测试问题")
        with patch(
            "services.agentic_rag.rewrite.rewrite_query",
            new_callable=AsyncMock,
            return_value="",
        ):
            result = await rewrite_node(state)

        assert result["rewritten_query"] == "测试问题"

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_original(self):
        """LLM 抛异常 → with_retry 兜底返回原问题。"""
        state = _make_state("原始问题")
        with patch(
            "services.agentic_rag.rewrite.rewrite_query",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API down"),
        ):
            result = await rewrite_node(state)

        assert result["rewritten_query"] == "原始问题"

    @pytest.mark.asyncio
    async def test_trace_recorded(self):
        """验证 trace 记录了耗时和原文/改写结果。"""
        state = _make_state("问题")
        with patch(
            "services.agentic_rag.rewrite.rewrite_query",
            new_callable=AsyncMock,
            return_value="改写结果",
        ):
            result = await rewrite_node(state)

        trace = result["trace"]["rewrite"]
        assert "elapsed_ms" in trace
        assert trace["elapsed_ms"] >= 0
        assert trace["original"] == "问题"
        assert trace["rewritten"] == "改写结果"


# ── route_node ───────────────────────────────────────────


class TestRouteNode:
    """route_node — mock LLM 分类。"""

    @pytest.mark.asyncio
    async def test_greeting_skips_llm(self):
        """问候语命中关键词 → 不调 LLM，直接 direct_answer。"""
        state = _make_state("你好")
        state["rewritten_query"] = "你好"
        with patch(
            "services.agentic_rag.rewrite._classify_route",
            new_callable=AsyncMock,
        ) as mock_classify:
            result = await route_node(state)

        assert result["route_decision"] == "direct_answer"
        mock_classify.assert_not_called()  # 跳过 LLM

    @pytest.mark.asyncio
    async def test_long_professional_question_routes_to_deep(self):
        """长专业问题（>20 字）→ T10 路由 deep（多路检索 + reflexion）。"""
        state = _make_state("请详细介绍该候选人的工作经历、项目经验和技能特长")
        state["rewritten_query"] = "请详细介绍该候选人的工作经历、项目经验和技能特长"
        with patch(
            "services.agentic_rag.rewrite._classify_route",
            new_callable=AsyncMock,
        ) as mock_classify:
            result = await route_node(state)
        assert result["route_decision"] == "deep"
        mock_classify.assert_not_called()  # route_node 为启发式路由，不调 LLM 分类

    @pytest.mark.asyncio
    async def test_short_question_routes_to_fast(self):
        """短问题（≤20 字，非问候）→ T10 路由 fast（单路快路径）。"""
        state = _make_state("今天天气怎么样")
        state["rewritten_query"] = "今天天气怎么样"
        with patch(
            "services.agentic_rag.rewrite._classify_route",
            new_callable=AsyncMock,
        ) as mock_classify:
            result = await route_node(state)
        assert result["route_decision"] == "fast"
        mock_classify.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_node_ignores_llm_classifier(self):
        """route_node 为启发式路由，不再调用 _classify_route（LLM 分类已停用）。"""
        state = _make_state("请详细介绍该候选人的工作经历、项目经验和技能特长")
        state["rewritten_query"] = "请详细介绍该候选人的工作经历、项目经验和技能特长"
        with patch(
            "services.agentic_rag.rewrite._classify_route",
            new_callable=AsyncMock,
            return_value="direct_answer",  # 即使 LLM 分类器返回 direct_answer 也被忽略
        ) as mock_classify:
            result = await route_node(state)
        assert result["route_decision"] == "deep"
        mock_classify.assert_not_called()

    @pytest.mark.asyncio
    async def test_classify_route_invalid_value_defaults_search(self):
        """_classify_route 收到非法 LLM 输出 → 返回 search。"""
        with patch(
            "services.agentic_rag.rewrite.llm_generate",
            new_callable=AsyncMock,
            return_value="不知道",
        ):
            result = await _classify_route("模糊问题")
        assert result == "search"

    @pytest.mark.asyncio
    async def test_trace_recorded(self):
        """验证 route trace 包含 decision。"""
        state = _make_state("你好")
        state["rewritten_query"] = "你好"
        with patch(
            "services.agentic_rag.rewrite._classify_route",
            new_callable=AsyncMock,
        ):
            result = await route_node(state)

        assert "route" in result["trace"]
        assert result["trace"]["route"]["decision"] == "direct_answer"

    @pytest.mark.asyncio
    async def test_uses_rewritten_query_over_original(self):
        """route_node 用 rewritten_query 判定路由：原问题短 → 改写后变长 → deep。"""
        state = _make_state("他")  # 原问题短，含指代
        state["rewritten_query"] = "请详细介绍该候选人的工作经历、项目经验和技能特长"  # 改写后变长
        with patch(
            "services.agentic_rag.rewrite._classify_route",
            new_callable=AsyncMock,
        ):
            result = await route_node(state)

        # 长度判定应基于改写后的查询（>20 字 → deep），而非原问题
        assert result["route_decision"] == "deep"
