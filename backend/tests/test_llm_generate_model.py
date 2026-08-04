"""
llm_generate 模型参数测试 — TDD 驱动

验证 llm_generate 能接受可选的 model 参数，
各 Agentic RAG 节点（evaluate/rewrite/route/reflection）
可指定 JUDGE_MODEL，不再硬编码 CHAT_MODEL。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings


class TestLlmGenerateModelParam:
    """llm_generate(model=...) 参数测试"""

    @pytest.mark.asyncio
    async def test_uses_chat_model_by_default(self):
        """默认使用 settings.CHAT_MODEL"""
        from services.rag import pipeline as pipeline_mod

        mock_client = AsyncMock()
        mock_completion = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "default model response"
        mock_completion.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        # 必须用 patch.object 恢复，直接赋值会污染后续所有 llm_generate 调用
        with patch.object(pipeline_mod, "get_chat_client", return_value=mock_client):
            result = await pipeline_mod.llm_generate("system prompt", "user message")

        assert result == "default model response"
        mock_client.chat.completions.create.assert_called_once()
        args, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["model"] == settings.CHAT_MODEL, (
            f"期望 model={settings.CHAT_MODEL!r}, 实际 model={kwargs.get('model')!r}"
        )

    @pytest.mark.asyncio
    async def test_accepts_custom_model_parameter(self):
        """传入 model 参数时应使用该模型而非 CHAT_MODEL"""
        from services.rag import pipeline as pipeline_mod

        mock_client = AsyncMock()
        mock_completion = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "custom model response"
        mock_completion.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        # 必须用 patch.object 恢复，直接赋值会污染后续所有 llm_generate 调用
        with patch.object(pipeline_mod, "get_chat_client", return_value=mock_client):
            result = await pipeline_mod.llm_generate(
                "system prompt", "user message", model="deepseek-v4-flash"
            )

        assert result == "custom model response"
        mock_client.chat.completions.create.assert_called_once()
        args, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["model"] == "deepseek-v4-flash", (
            f"期望 model='deepseek-v4-flash', 实际 model={kwargs.get('model')!r}"
        )


class TestEvaluateNodeUsesJudgeModel:
    """evaluate_node 应通过 model 参数使用 JUDGE_MODEL"""

    @pytest.mark.asyncio
    async def test_evaluate_passes_judge_model_to_llm(self):
        """evaluate_node 调用 llm_generate 时应传入 JUDGE_MODEL"""
        from services.agentic_rag import generate as generate_mod
        from services.agentic_rag.state import AgenticRAGState

        mock_llm = AsyncMock(return_value='{"completeness": 8, "accuracy": 8, "source_credibility": 7, "feedback": "good"}')

        state: AgenticRAGState = {
            "question": "test question",
            "resume_id": 1,
            "rewritten_query": "test rewritten",
            "route_decision": "search",
            "chunks": [{"text": "test content", "chunk_index": 0, "section": "test"}],
            "search_round": 1,
            "answer": "test answer",
            "sources": [{"text": "test content", "chunk_index": 0, "section": "test", "rerank_score": 0.8}],
            "eval_score": 0.0,
            "eval_feedback": "",
            "should_retry": False,
            "completeness_score": 0.0,
            "accuracy_score": 0.0,
            "source_credibility_score": 0.0,
            "eval_forced": False,
            "reflection_result": "",
            "missing_info": [],
            "supplement_queries": [],
            "reflection_round": 0,
            "final_answer": "",
            "final_sources": [],
            "trace": {"generate": {"rejected": False}},
            "tool_errors": [],
        }

        with patch.object(settings, "JUDGE_ENABLED", True), \
             patch.object(generate_mod, "llm_generate", mock_llm):
            result = await generate_mod.evaluate_node(state)

        mock_llm.assert_called_once()
        args, kwargs = mock_llm.call_args
        assert "model" in kwargs, (
            f"evaluate_node 未传 model 参数，实际 kwargs keys={list(kwargs.keys())}"
        )
        assert kwargs["model"] == settings.JUDGE_MODEL, (
            f"期望 model={settings.JUDGE_MODEL!r}, 实际 model={kwargs.get('model')!r}"
        )


class TestRewriteNodeUsesJudgeModel:
    """rewrite_node 应通过 model 参数使用 JUDGE_MODEL"""

    @pytest.mark.asyncio
    async def test_rewrite_node_passes_judge_model(self):
        """rewrite_node 调用 rewrite_query 时应传入 JUDGE_MODEL"""
        from services.agentic_rag import rewrite as rewrite_mod
        from services.agentic_rag.state import AgenticRAGState

        mock_rewrite = AsyncMock(return_value="rewritten question")

        state: AgenticRAGState = {
            "question": "test question",
            "resume_id": 1,
            "rewritten_query": "",
            "route_decision": "search",
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
            "eval_forced": False,
            "reflection_result": "",
            "missing_info": [],
            "supplement_queries": [],
            "reflection_round": 0,
            "final_answer": "",
            "final_sources": [],
            "trace": {},
            "tool_errors": [],
        }

        with patch.object(settings, "JUDGE_ENABLED", True), \
             patch.object(rewrite_mod, "rewrite_query", mock_rewrite):
            result = await rewrite_mod.rewrite_node(state)

        mock_rewrite.assert_called_once()
        args, kwargs = mock_rewrite.call_args
        assert "model" in kwargs, (
            f"rewrite_node 未传 model 参数，实际 kwargs keys={list(kwargs.keys())}"
        )
        assert kwargs["model"] == settings.JUDGE_MODEL, (
            f"期望 model={settings.JUDGE_MODEL!r}, 实际 model={kwargs.get('model')!r}"
        )


class TestSelfReflectionNodeUsesJudgeModel:
    """self_reflection_node 应通过 model 参数使用 JUDGE_MODEL"""

    @pytest.mark.asyncio
    async def test_self_reflection_passes_judge_model(self):
        """self_reflection_node 调用 llm_generate 时应传入 JUDGE_MODEL"""
        from services.agentic_rag import reflection as reflection_mod
        from services.agentic_rag.state import AgenticRAGState

        mock_llm = AsyncMock(return_value='{"reflection": "good", "missing_info": ["more"], "supplement_queries": ["query1"]}')

        state: AgenticRAGState = {
            "question": "test question",
            "resume_id": 1,
            "rewritten_query": "test rewritten",
            "route_decision": "search",
            "chunks": [{"text": "test", "chunk_index": 0, "section": "test"}],
            "search_round": 1,
            "answer": "test answer",
            "sources": [{"text": "test", "chunk_index": 0, "section": "test", "rerank_score": 0.5}],
            "eval_score": 0.4,
            "eval_feedback": "not complete",
            "should_retry": True,
            "completeness_score": 0.4,
            "accuracy_score": 0.5,
            "source_credibility_score": 0.5,
            "eval_forced": False,
            "reflection_result": "",
            "missing_info": [],
            "supplement_queries": [],
            "reflection_round": 0,
            "final_answer": "",
            "final_sources": [],
            "trace": {},
            "tool_errors": [],
        }

        with patch.object(settings, "JUDGE_ENABLED", True), \
             patch.object(reflection_mod, "llm_generate", mock_llm):
            result = await reflection_mod.self_reflection_node(state)

        mock_llm.assert_called_once()
        args, kwargs = mock_llm.call_args
        assert "model" in kwargs, (
            f"self_reflection_node 未传 model 参数，实际 kwargs keys={list(kwargs.keys())}"
        )
        assert kwargs["model"] == settings.JUDGE_MODEL, (
            f"期望 model={settings.JUDGE_MODEL!r}, 实际 model={kwargs.get('model')!r}"
        )


class TestRouteNodeUsesJudgeModel:
    """route_node 应通过 model 参数使用 JUDGE_MODEL"""

    @pytest.mark.asyncio
    async def test_rewrite_query_fallback_on_failure(self):
        """rewrite_query 重试耗尽后应返回原问题兜底"""
        from services.rag import pipeline as pipeline_mod

        mock_llm = AsyncMock(side_effect=Exception("API error"))

        with patch.object(pipeline_mod, "llm_generate", mock_llm):
            result = await pipeline_mod.rewrite_query("原问题", model="test-model")

        assert result == "原问题", f"期望返回原问题，实际：{result!r}"

    @pytest.mark.asyncio
    async def test_route_node_passes_judge_model(self):
        """_classify_route 调用 llm_generate 时应传入 JUDGE_MODEL

        route_node 已改为启发式路由（T10），不再调用 _classify_route；
        此处直接验证 LLM 路由分类器仍透传 JUDGE_MODEL。
        """
        from services.agentic_rag import rewrite as rewrite_mod

        mock_llm = AsyncMock(return_value="search")

        with patch.object(settings, "JUDGE_ENABLED", True), \
             patch.object(rewrite_mod, "llm_generate", mock_llm):
            # _classify_route 的 model 参数由调用方决定（route_node 传 JUDGE_MODEL），
            # 此处显式传入以验证「透传」语义。
            result = await rewrite_mod._classify_route(
                "tell me about Python skills", model=settings.JUDGE_MODEL
            )

        assert result == "search"
        mock_llm.assert_called_once()
        args, kwargs = mock_llm.call_args
        assert "model" in kwargs, (
            f"_classify_route 未传 model 参数，实际 kwargs keys={list(kwargs.keys())}"
        )
        assert kwargs["model"] == settings.JUDGE_MODEL, (
            f"期望 model={settings.JUDGE_MODEL!r}, 实际 model={kwargs.get('model')!r}"
        )
