"""
Agentic RAG — generate_node + evaluate_node 单元测试。

全部 mock LLM 调用，不依赖外部 API。
运行: python -m pytest tests/test_agentic_generate.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.agentic_rag.generate import (
    generate_node,
    evaluate_node,
    _extract_sources,
    _parse_eval_response,
    _build_eval_user,
)
from services.agentic_rag.state import AgenticRAGState


# ── 辅助 ──────────────────────────────────────────────────


def _make_state(**overrides) -> AgenticRAGState:
    """构造最小 AgenticRAGState。"""
    base: AgenticRAGState = {
        "question": "候选人有哪些技能",
        "resume_id": 1,
        "rewritten_query": "候选人的专业技能有哪些",
        "route_decision": "search",
        "chunks": [
            {
                "text": "精通 Python、FastAPI",
                "section": "专业技能",
                "chunk_index": 0,
                "rerank_score": 0.9,
            },
            {"text": "3年开发经验", "section": "工作经历", "chunk_index": 1, "rerank_score": 0.7},
        ],
        "search_round": 1,
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


# ── _extract_sources ──────────────────────────────────────


class TestExtractSources:
    """_extract_sources 纯逻辑测试。"""

    def test_extracts_basic_fields(self):
        chunks = [
            {"text": "内容1", "section": "技能", "chunk_index": 0, "rerank_score": 0.8},
        ]
        sources = _extract_sources(chunks)
        assert len(sources) == 1
        assert sources[0]["text"] == "内容1"
        assert sources[0]["section"] == "技能"
        assert sources[0]["chunk_index"] == 0
        assert sources[0]["rerank_score"] == 0.8

    def test_handles_missing_fields(self):
        """缺失字段不抛异常，也不伪造 provenance。"""
        chunks = [{"text": "内容"}]
        sources = _extract_sources(chunks)
        assert len(sources) == 1
        assert "chunk_index" not in sources[0]
        assert "section" not in sources[0]
        assert "rerank_score" not in sources[0]

    def test_empty_chunks(self):
        assert _extract_sources([]) == []

    def test_preserves_order(self):
        chunks = [
            {"text": "A", "chunk_index": 2},
            {"text": "B", "chunk_index": 5},
        ]
        sources = _extract_sources(chunks)
        assert [s["text"] for s in sources] == ["A", "B"]


# ── _parse_eval_response ──────────────────────────────────


class TestParseEvalResponse:
    """_parse_eval_response 防御性解析测试（细粒度评分）。"""

    def test_valid_json_with_dimensions(self):
        """完整 JSON：三个维度 + 反馈。"""
        raw = '{"completeness": 8, "accuracy": 9, "source_credibility": 7, "feedback": "回答准确完整"}'
        completeness, accuracy, source_credibility, composite, feedback = _parse_eval_response(raw)
        assert completeness == 0.8
        assert accuracy == 0.9
        assert source_credibility == 0.7
        assert feedback == "回答准确完整"
        # 综合分数：0.8*0.4 + 0.9*0.4 + 0.7*0.2 = 0.32 + 0.36 + 0.14 = 0.82
        assert abs(composite - 0.82) < 0.01

    def test_scores_clamped_to_0_1(self):
        """分数应被归一化到 0-1。"""
        raw = '{"completeness": 10, "accuracy": 10, "source_credibility": 10, "feedback": ""}'
        completeness, accuracy, source_credibility, composite, _ = _parse_eval_response(raw)
        assert completeness == 1.0
        assert accuracy == 1.0
        assert source_credibility == 1.0
        assert composite == 1.0

    def test_empty_string(self):
        completeness, accuracy, source_credibility, composite, feedback = _parse_eval_response("")
        assert completeness == 0.5
        assert accuracy == 0.5
        assert source_credibility == 0.5
        assert composite == 0.5
        assert feedback == "评估返回为空"

    def test_invalid_json_fallback(self):
        """非 JSON 格式应降级提取。"""
        raw = 'some text "completeness": 7 "accuracy": 8 "source_credibility": 6 other text'
        completeness, accuracy, source_credibility, composite, _ = _parse_eval_response(raw)
        assert completeness == 0.7
        assert accuracy == 0.8
        assert source_credibility == 0.6

    def test_malformed_json(self):
        """损坏的 JSON 应降级。"""
        completeness, accuracy, source_credibility, composite, _ = _parse_eval_response(
            "{broken json"
        )
        assert 0.0 <= completeness <= 1.0
        assert 0.0 <= accuracy <= 1.0
        assert 0.0 <= source_credibility <= 1.0

    def test_missing_fields_defaults(self):
        """JSON 缺少字段 → 默认 5/10。"""
        raw = '{"feedback": "ok"}'
        completeness, accuracy, source_credibility, composite, _ = _parse_eval_response(raw)
        assert completeness == 0.5
        assert accuracy == 0.5
        assert source_credibility == 0.5

    def test_float_scores(self):
        """浮点数分数应正确处理。"""
        raw = '{"completeness": 7.5, "accuracy": 8.5, "source_credibility": 6.5, "feedback": ""}'
        completeness, accuracy, source_credibility, composite, _ = _parse_eval_response(raw)
        assert completeness == 0.75
        assert accuracy == 0.85
        assert source_credibility == 0.65


# ── _build_eval_user ──────────────────────────────────────


class TestBuildEvalUser:
    """_build_eval_user 构建 prompt 测试。"""

    def test_contains_question_and_answer(self):
        sources = [{"section": "技能", "text": "Python"}]
        result = _build_eval_user("问题", "回答", sources)
        assert "问题" in result
        assert "回答" in result

    def test_truncates_long_source_text(self):
        """来源文本应截断到 200 字符。"""
        long_text = "A" * 500
        sources = [{"section": "测试", "text": long_text}]
        result = _build_eval_user("Q", "A", sources)
        assert "A" * 500 not in result  # 被截断
        assert "A" * 200 in result

    def test_limits_to_5_sources(self):
        """最多 5 条来源。"""
        sources = [{"section": f"S{i}", "text": f"T{i}"} for i in range(10)]
        result = _build_eval_user("Q", "A", sources)
        assert "[来源 6]" not in result
        assert "[来源 5]" in result


# ── generate_node ─────────────────────────────────────────


class TestGenerateNode:
    """generate_node — mock LLM 调用。"""

    @pytest.mark.asyncio
    async def test_generates_answer_from_chunks(self):
        """正常生成：有 chunks → 调 LLM → 返回 answer + sources。"""
        state = _make_state()
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value="候选人精通 Python 和 FastAPI，有3年开发经验。",
        ):
            result = await generate_node(state)

        assert "候选人" in result["answer"]
        assert len(result["sources"]) == 2
        assert "generate" in result["trace"]
        assert result["trace"]["generate"]["rejected"] is False

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_rejection(self):
        """无 chunks → 拒答。"""
        state = _make_state(chunks=[])
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
        ) as mock_llm:
            result = await generate_node(state)

        assert "未提及" in result["answer"]
        assert result["sources"] == []
        assert result["trace"]["generate"]["rejected"] is True
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_rerank_score_returns_rejection(self):
        """rerank 分数过低 → 拒答。"""
        state = _make_state(
            chunks=[
                {"text": "内容", "section": "测试", "chunk_index": 0, "rerank_score": 0.1},
            ]
        )
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
        ) as mock_llm:
            result = await generate_node(state)

        assert "未提及" in result["answer"]
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_fallback(self):
        """LLM 失败 → with_retry 兜底。"""
        state = _make_state()
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API down"),
        ):
            result = await generate_node(state)

        assert "服务暂时不可用" in result["answer"]

    @pytest.mark.asyncio
    async def test_uses_rewritten_query(self):
        """应使用 rewritten_query 而非 question。"""
        state = _make_state(question="他", rewritten_query="候选人的技能")
        with (
            patch(
                "services.agentic_rag.generate._build_generate_prompt",
                return_value={"system": "s", "user": "u"},
            ) as mock_build,
            patch(
                "services.agentic_rag.generate.llm_generate",
                new_callable=AsyncMock,
                return_value="答案",
            ),
        ):
            await generate_node(state)

        # _build_generate_prompt 应收到 rewritten_query
        mock_build.assert_called_once()
        call_args = mock_build.call_args
        assert call_args[0][1] == "候选人的技能"  # 第二个参数是 query

    @pytest.mark.asyncio
    async def test_preserves_existing_trace(self):
        """应保留 state 中已有的 trace 数据。"""
        state = _make_state(trace={"rewrite": {"elapsed_ms": 100}})
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value="答案",
        ):
            result = await generate_node(state)

        assert "rewrite" in result["trace"]
        assert "generate" in result["trace"]

    @pytest.mark.asyncio
    async def test_trace_records_metadata(self):
        """trace 应记录 chunk_count 和 answer_length。"""
        state = _make_state()
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value="测试答案",
        ):
            result = await generate_node(state)

        gen_trace = result["trace"]["generate"]
        assert gen_trace["chunk_count"] == 2
        assert gen_trace["answer_length"] == 4  # "测试答案"
        assert gen_trace["elapsed_ms"] >= 0

    @pytest.mark.asyncio
    async def test_sources_contain_chunk_info(self):
        """sources 应包含 chunk 的关键信息。"""
        state = _make_state()
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value="答案",
        ):
            result = await generate_node(state)

        assert result["sources"][0]["text"] == "精通 Python、FastAPI"
        assert result["sources"][0]["section"] == "专业技能"
        assert result["sources"][0]["rerank_score"] == 0.9


# ── evaluate_node ─────────────────────────────────────────


class TestEvaluateNode:
    """evaluate_node — mock LLM 调用（细粒度评分）。"""

    @pytest.mark.asyncio
    async def test_high_score_passes(self):
        """高分回答 → should_retry=False。"""
        state = _make_state(answer="候选人精通 Python")
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value='{"completeness": 9, "accuracy": 9, "source_credibility": 8, "feedback": "准确完整"}',
        ):
            result = await evaluate_node(state)

        assert result["eval_score"] > 0.8
        assert result["should_retry"] is False
        assert result["eval_feedback"] == "准确完整"
        assert result["completeness_score"] == 0.9
        assert result["accuracy_score"] == 0.9
        assert result["source_credibility_score"] == 0.8

    @pytest.mark.asyncio
    async def test_low_score_triggers_retry(self):
        """低分回答 → should_retry=True。"""
        state = _make_state(answer="不确定")
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value='{"completeness": 3, "accuracy": 4, "source_credibility": 2, "feedback": "回答不完整"}',
        ):
            result = await evaluate_node(state)

        assert result["eval_score"] < 0.6
        assert result["should_retry"] is True
        assert result["eval_feedback"] == "回答不完整"
        assert result["completeness_score"] == 0.3
        assert result["accuracy_score"] == 0.4
        assert result["source_credibility_score"] == 0.2

    @pytest.mark.asyncio
    async def test_boundary_score_passes(self):
        """恰好 6 分（阈值）→ 不重试。"""
        state = _make_state(answer="基本回答")
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value='{"completeness": 6, "accuracy": 6, "source_credibility": 6, "feedback": "及格"}',
        ):
            result = await evaluate_node(state)

        assert result["eval_score"] == 0.6
        assert result["should_retry"] is False

    @pytest.mark.asyncio
    async def test_just_below_threshold_retries(self):
        """略低于阈值 → 重试。"""
        state = _make_state(answer="部分回答")
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value='{"completeness": 3, "accuracy": 4, "source_credibility": 4, "feedback": "不够完整"}',
        ):
            result = await evaluate_node(state)

        assert result["eval_score"] < 0.4
        assert result["should_retry"] is True

    @pytest.mark.asyncio
    async def test_rejection_skips_evaluation(self):
        """拒答答案 → 跳过评估，但允许 Reflexion 补充检索。"""
        state = _make_state(
            answer="抱歉，简历中未提及该信息。",
            trace={"generate": {"rejected": True}},
        )
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
        ) as mock_llm:
            result = await evaluate_node(state)

        assert result["eval_score"] == 0.0
        # 零召回是最需要补充检索（supplement_queries）的场景，
        # 不再短路——轮数未超限时应触发反思重试。
        assert result["should_retry"] is True
        assert result["trace"]["evaluate"]["skipped"] is True
        assert result["completeness_score"] == 0.0
        assert result["accuracy_score"] == 0.0
        assert result["source_credibility_score"] == 0.0
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_answer_skips_evaluation(self):
        """空答案 → 跳过评估，但允许 Reflexion 补充检索。"""
        state = _make_state(answer="")
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
        ) as mock_llm:
            result = await evaluate_node(state)

        assert result["eval_score"] == 0.0
        assert result["should_retry"] is True
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_retries_forces_pass(self):
        """超过最大重试次数 → 强制通过，不重试。"""
        state = _make_state(answer="最终尝试", search_round=3)
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
        ) as mock_llm:
            result = await evaluate_node(state)

        assert result["should_retry"] is False
        assert result["trace"]["evaluate"]["skipped"] is True
        assert result["trace"]["evaluate"]["reason"] == "max_retries_reached"
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_fallback_score(self):
        """LLM 失败 → with_retry 兜底，返回中等分数。"""
        state = _make_state(answer="答案")
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API down"),
        ):
            result = await evaluate_node(state)

        # with_retry fallback → _parse_eval_response 解析 fallback JSON
        assert 0.0 <= result["eval_score"] <= 1.0
        assert result["trace"]["evaluate"]["skipped"] is False

    @pytest.mark.asyncio
    async def test_trace_recorded(self):
        """trace 应包含评估节点信息（细粒度）。"""
        state = _make_state(answer="答案")
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value='{"completeness": 7, "accuracy": 8, "source_credibility": 6, "feedback": "ok"}',
        ):
            result = await evaluate_node(state)

        trace = result["trace"]["evaluate"]
        assert trace["elapsed_ms"] >= 0
        assert trace["completeness"] == 0.7
        assert trace["accuracy"] == 0.8
        assert trace["source_credibility"] == 0.6
        assert trace["should_retry"] is False
        assert trace["skipped"] is False

    @pytest.mark.asyncio
    async def test_preserves_existing_trace(self):
        """应保留 state 中已有的 trace 数据。"""
        state = _make_state(
            answer="答案",
            trace={"rewrite": {}, "search": {}, "generate": {}},
        )
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value='{"completeness": 8, "accuracy": 8, "source_credibility": 8, "feedback": "good"}',
        ):
            result = await evaluate_node(state)

        assert "rewrite" in result["trace"]
        assert "search" in result["trace"]
        assert "generate" in result["trace"]
        assert "evaluate" in result["trace"]

    @pytest.mark.asyncio
    async def test_uses_rewritten_query_for_eval(self):
        """评估应使用 rewritten_query 而非 question。"""
        state = _make_state(
            question="他",
            rewritten_query="候选人的技能",
            answer="答案",
        )
        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
            return_value='{"completeness": 7, "accuracy": 7, "source_credibility": 7, "feedback": "ok"}',
        ) as mock_llm:
            await evaluate_node(state)

        # 验证传给 LLM 的 prompt 包含 rewritten_query
        eval_user = mock_llm.call_args[0][1]  # 第二个参数是 user prompt
        assert "候选人的技能" in eval_user


# ── Generate + Evaluate 联动 ──────────────────────────────


class TestGenerateEvaluatePipeline:
    """generate_node → evaluate_node 全流程状态应正确流转。"""

    @pytest.mark.asyncio
    async def test_full_pipeline_good_answer(self):
        """好答案 → generate → evaluate → should_retry=False。"""
        state = _make_state()

        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
        ) as mock_llm:
            # generate 调用一次，evaluate 调用一次
            mock_llm.side_effect = [
                "候选人精通 Python 和 FastAPI，有3年开发经验。",
                '{"completeness": 9, "accuracy": 9, "source_credibility": 8, "feedback": "准确完整"}',
            ]
            gen_result = await generate_node(state)
            state.update(gen_result)
            eval_result = await evaluate_node(state)
            state.update(eval_result)

        assert state["answer"] == "候选人精通 Python 和 FastAPI，有3年开发经验。"
        assert len(state["sources"]) == 2
        assert state["eval_score"] > 0.8
        assert state["should_retry"] is False
        assert "generate" in state["trace"]
        assert "evaluate" in state["trace"]

    @pytest.mark.asyncio
    async def test_full_pipeline_poor_answer_triggers_retry(self):
        """差答案 → generate → evaluate → should_retry=True。"""
        state = _make_state()

        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.side_effect = [
                "不太确定。",
                '{"completeness": 3, "accuracy": 4, "source_credibility": 2, "feedback": "回答不完整"}',
            ]
            gen_result = await generate_node(state)
            state.update(gen_result)
            eval_result = await evaluate_node(state)
            state.update(eval_result)

        assert state["should_retry"] is True
        assert state["eval_score"] < 0.6

    @pytest.mark.asyncio
    async def test_rejection_skips_both_generate_and_evaluate(self):
        """无 chunks → generate 拒答 → evaluate 跳过。"""
        state = _make_state(chunks=[])

        with patch(
            "services.agentic_rag.generate.llm_generate",
            new_callable=AsyncMock,
        ) as mock_llm:
            gen_result = await generate_node(state)
            state.update(gen_result)
            eval_result = await evaluate_node(state)
            state.update(eval_result)

        assert "未提及" in state["answer"]
        # 零召回应触发 Reflexion 补充检索，而非短路
        assert state["should_retry"] is True
        assert state["eval_score"] == 0.0
        # LLM 不应被调用（generate 拒答 + evaluate 跳过）
        mock_llm.assert_not_called()
