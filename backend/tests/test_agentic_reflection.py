"""
Agentic RAG — self_reflection_node 单元测试（Reflexion核心）。

测试 Self-Reflection 节点的反思分析、缺失识别、查询生成能力。
运行: python -m pytest tests/test_agentic_reflection.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.agentic_rag.reflection import (
    self_reflection_node,
    _parse_reflection_response,
    _build_reflection_user,
    _MAX_SUPPLEMENT_QUERIES,
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
        ],
        "search_round": 1,
        "answer": "候选人精通 Python",
        "sources": [{"section": "专业技能", "text": "精通 Python", "rerank_score": 0.9}],
        "eval_score": 0.3,
        "eval_feedback": "回答不完整，缺少 FastAPI 和其他技能信息",
        "should_retry": True,
        "completeness_score": 0.3,
        "accuracy_score": 0.6,
        "source_credibility_score": 0.8,
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


# ── _parse_reflection_response ─────────────────────────────


class TestParseReflectionResponse:
    """_parse_reflection_response 防御性解析测试。"""

    def test_valid_json(self):
        raw = '{"reflection": "答案不完整", "missing_info": ["FastAPI经验"], "supplement_queries": ["FastAPI项目经验"]}'
        reflection, missing, queries = _parse_reflection_response(raw)
        assert reflection == "答案不完整"
        assert missing == ["FastAPI经验"]
        assert queries == ["FastAPI项目经验"]

    def test_multiple_items(self):
        """多个缺失信息和查询。"""
        raw = '{"reflection": "多个缺失", "missing_info": ["技能1", "技能2", "技能3"], "supplement_queries": ["查询1", "查询2"]}'
        reflection, missing, queries = _parse_reflection_response(raw)
        assert len(missing) == 3
        assert len(queries) == 2

    def test_empty_string(self):
        reflection, missing, queries = _parse_reflection_response("")
        assert reflection == "解析失败，无法分析"
        assert missing == ["无法识别缺失信息"]
        assert queries == []

    def test_invalid_json_fallback(self):
        """非 JSON 格式应降级提取。"""
        raw = 'some text "reflection": "测试反思" "missing_info": ["缺失1"] "supplement_queries": ["查询1"] other text'
        reflection, missing, queries = _parse_reflection_response(raw)
        assert reflection == "测试反思"
        assert "缺失1" in missing
        assert "查询1" in queries

    def test_malformed_json(self):
        """损坏的 JSON 应降级。"""
        reflection, missing, queries = _parse_reflection_response("{broken json")
        assert reflection == "解析失败，无法分析"
        assert isinstance(missing, list)
        assert isinstance(queries, list)

    def test_limits_supplement_queries(self):
        """最多 _MAX_SUPPLEMENT_QUERIES 个查询。"""
        import json

        queries = [f"查询{i}" for i in range(10)]
        raw = json.dumps({"reflection": "test", "missing_info": [], "supplement_queries": queries})
        _, _, result_queries = _parse_reflection_response(raw)
        assert len(result_queries) == _MAX_SUPPLEMENT_QUERIES

    def test_float_values(self):
        """浮点数应正确处理。"""
        raw = '{"reflection": 123, "missing_info": [], "supplement_queries": []}'
        reflection, _, _ = _parse_reflection_response(raw)
        assert reflection == "123"


# ── _build_reflection_user ─────────────────────────────────


class TestBuildReflectionUser:
    """_build_reflection_user 构建 prompt 测试。"""

    def test_contains_all_parameters(self):
        sources = [{"section": "技能", "text": "Python"}]
        result = _build_reflection_user(
            question="问题",
            answer="回答",
            sources=sources,
            eval_feedback="反馈",
            completeness_score=0.7,
            accuracy_score=0.8,
            source_credibility_score=0.6,
            previous_reflections=[],
        )
        assert "问题" in result
        assert "回答" in result
        assert "反馈" in result
        assert "70.0%" in result  # completeness_score formatted as percentage
        assert "80.0%" in result  # accuracy_score
        assert "60.0%" in result  # source_credibility_score

    def test_includes_previous_reflections(self):
        """应包含之前的反思（避免重复）。"""
        sources = [{"section": "技能", "text": "Python"}]
        result = _build_reflection_user(
            question="Q",
            answer="A",
            sources=sources,
            eval_feedback="",
            completeness_score=0.5,
            accuracy_score=0.5,
            source_credibility_score=0.5,
            previous_reflections=["第一次反思：缺少信息"],
        )
        assert "第一次反思：缺少信息" in result
        assert "之前的反思（避免重复）" in result

    def test_limits_previous_reflections(self):
        """最多保留最近 2 轮反思。"""
        sources = [{"section": "技能", "text": "Python"}]
        reflections = ["反思1", "反思2", "反思3"]
        result = _build_reflection_user(
            question="Q",
            answer="A",
            sources=sources,
            eval_feedback="",
            completeness_score=0.5,
            accuracy_score=0.5,
            source_credibility_score=0.5,
            previous_reflections=reflections,
        )
        # 应包含最近2轮
        assert "反思2" in result
        assert "反思3" in result
        # 不应包含第1轮
        assert "反思1" not in result

    def test_truncates_source_text(self):
        """来源文本应截断。"""
        long_text = "A" * 500
        sources = [{"section": "测试", "text": long_text}]
        result = _build_reflection_user(
            question="Q",
            answer="A",
            sources=sources,
            eval_feedback="",
            completeness_score=0.5,
            accuracy_score=0.5,
            source_credibility_score=0.5,
            previous_reflections=[],
        )
        assert "A" * 500 not in result
        assert "A" * 150 in result


# ── self_reflection_node ───────────────────────────────────


class TestSelfReflectionNode:
    """self_reflection_node — mock LLM 调用。"""

    @pytest.mark.asyncio
    async def test_generates_reflection(self):
        """正常反思：分析缺失信息，生成补充查询。"""
        state = _make_state()
        with patch(
            "services.agentic_rag.reflection.llm_generate",
            new_callable=AsyncMock,
            return_value='{"reflection": "答案缺少FastAPI相关经验", "missing_info": ["FastAPI项目经验"], "supplement_queries": ["FastAPI项目开发经验"]}',
        ):
            result = await self_reflection_node(state)

        assert result["reflection_result"] == "答案缺少FastAPI相关经验"
        assert result["missing_info"] == ["FastAPI项目经验"]
        assert result["supplement_queries"] == ["FastAPI项目开发经验"]
        assert result["reflection_round"] == 1
        assert "self_reflection_1" in result["trace"]

    @pytest.mark.asyncio
    async def test_increments_round(self):
        """反思轮次应递增。"""
        state = _make_state(reflection_round=1)
        with patch(
            "services.agentic_rag.reflection.llm_generate",
            new_callable=AsyncMock,
            return_value='{"reflection": "继续分析", "missing_info": [], "supplement_queries": []}',
        ):
            result = await self_reflection_node(state)

        assert result["reflection_round"] == 2

    @pytest.mark.asyncio
    async def test_collects_previous_reflections(self):
        """应收集之前的反思历史。"""
        state = _make_state(
            reflection_round=2,
            trace={
                "self_reflection_1": {"reflection": "第一次反思"},
                "self_reflection_2": {"reflection": "第二次反思"},
            },
        )
        with patch(
            "services.agentic_rag.reflection.llm_generate",
            new_callable=AsyncMock,
            return_value='{"reflection": "继续分析", "missing_info": [], "supplement_queries": []}',
        ) as mock_llm:
            await self_reflection_node(state)

        # 验证 prompt 包含之前的反思
        user_prompt = mock_llm.call_args[0][1]
        assert "第一次反思" in user_prompt
        assert "第二次反思" in user_prompt

    @pytest.mark.asyncio
    async def test_llm_failure_returns_fallback(self):
        """LLM 失败 → with_retry 兜底。"""
        state = _make_state()
        with patch(
            "services.agentic_rag.reflection.llm_generate",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API down"),
        ):
            result = await self_reflection_node(state)

        assert "反思服务暂时不可用" in result["reflection_result"]
        assert result["missing_info"] == []
        assert result["supplement_queries"] == []

    @pytest.mark.asyncio
    async def test_preserves_existing_trace(self):
        """应保留 state 中已有的 trace 数据。"""
        state = _make_state(trace={"rewrite": {}, "search": {}})
        with patch(
            "services.agentic_rag.reflection.llm_generate",
            new_callable=AsyncMock,
            return_value='{"reflection": "test", "missing_info": [], "supplement_queries": []}',
        ):
            result = await self_reflection_node(state)

        assert "rewrite" in result["trace"]
        assert "search" in result["trace"]
        assert "self_reflection_1" in result["trace"]

    @pytest.mark.asyncio
    async def test_uses_rewritten_query(self):
        """应使用 rewritten_query 而非 question。"""
        state = _make_state(question="他", rewritten_query="候选人的技能")
        with patch(
            "services.agentic_rag.reflection.llm_generate",
            new_callable=AsyncMock,
            return_value='{"reflection": "test", "missing_info": [], "supplement_queries": []}',
        ) as mock_llm:
            await self_reflection_node(state)

        user_prompt = mock_llm.call_args[0][1]
        assert "候选人的技能" in user_prompt

    @pytest.mark.asyncio
    async def test_trace_records_metadata(self):
        """trace 应记录反思元数据。"""
        state = _make_state()
        with patch(
            "services.agentic_rag.reflection.llm_generate",
            new_callable=AsyncMock,
            return_value='{"reflection": "分析结果", "missing_info": ["缺失1", "缺失2"], "supplement_queries": ["查询1"]}',
        ):
            result = await self_reflection_node(state)

        trace = result["trace"]["self_reflection_1"]
        assert trace["elapsed_ms"] >= 0
        assert trace["missing_count"] == 2
        assert trace["query_count"] == 1
        assert "分析结果" in trace["reflection"]

    @pytest.mark.asyncio
    async def test_empty_answer_handles_gracefully(self):
        """空答案 → 正常反思（可能是因为检索失败）。"""
        state = _make_state(answer="", sources=[])
        with patch(
            "services.agentic_rag.reflection.llm_generate",
            new_callable=AsyncMock,
            return_value='{"reflection": "没有找到答案", "missing_info": ["所有信息"], "supplement_queries": ["重新搜索"]}',
        ):
            result = await self_reflection_node(state)

        assert result["reflection_result"] == "没有找到答案"
        assert len(result["supplement_queries"]) == 1


# ── Reflexion 完整流程 ─────────────────────────────────────


class TestReflexionPipeline:
    """Reflexion 完整流程：evaluate → self_reflection → search。"""

    @pytest.mark.asyncio
    async def test_reflexion_generates_supplement_queries(self):
        """低分答案 → 反思 → 生成补充查询 → 可用于下一轮检索。"""
        state = _make_state(
            answer="候选人精通 Python",
            eval_score=0.3,
            eval_feedback="缺少FastAPI和项目经验",
            should_retry=True,
            completeness_score=0.3,
            accuracy_score=0.6,
            source_credibility_score=0.8,
        )

        with patch(
            "services.agentic_rag.reflection.llm_generate",
            new_callable=AsyncMock,
            return_value='{"reflection": "答案缺少关键技能信息", "missing_info": ["FastAPI经验", "项目经历"], "supplement_queries": ["FastAPI项目开发经验", "简历中的项目经历"]}',
        ):
            reflection_result = await self_reflection_node(state)
            state.update(reflection_result)

        # 验证反思结果
        assert state["reflection_round"] == 1
        assert len(state["supplement_queries"]) == 2
        assert "FastAPI项目开发经验" in state["supplement_queries"]

        # 验证 search_node 可以使用这些查询
        # （search_node 的测试在 test_agentic_search.py 中）
