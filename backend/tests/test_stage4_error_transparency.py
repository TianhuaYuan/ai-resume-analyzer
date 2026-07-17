"""
阶段4 错误透传 — TDD 测试（RED → GREEN）。

覆盖：
  4.1  AgenticRAGState 新增 tool_errors 字段
  4.2  search_node / rerank_node 捕获子步骤异常并写入 tool_errors（不抛出）
  4.3  generate_node 在 tool_errors 非空时向 prompt 注入降级说明
  4.4  qa API 在 tool_errors 场景下 AnswerResponse.degraded == True

运行（仅本文件，避免触发 MySQL 集成测试）：
  cd /d/Project/ai-resume-analyzer/backend && .venv/Scripts/python.exe -m pytest tests/test_stage4_error_transparency.py -p no:cacheprovider -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from services.agentic_rag.state import AgenticRAGState
from services.agentic_rag.search import search_node, rerank_node
from services.agentic_rag.generate import generate_node


# ── 4.1 State 字段 ──────────────────────────────────────────

class TestStateToolErrorsField:
    def test_tool_errors_in_annotations(self):
        """AgenticRAGState 应声明 tool_errors: list[dict]。"""
        assert "tool_errors" in AgenticRAGState.__annotations__
        assert AgenticRAGState.__annotations__["tool_errors"] == list[dict]

    @pytest.mark.asyncio
    async def test_tool_errors_default_empty_at_runtime(self):
        """运行时构造的 state 即使不带 tool_errors，节点也应安全以空列表处理。"""
        state = {
            "question": "q", "resume_id": 1, "rewritten_query": "q",
            "route_decision": "search", "chunks": [], "search_round": 0, "trace": {},
        }
        # nodes 使用 state.get("tool_errors", [])，不应因缺字段而 KeyError
        with patch("services.agentic_rag.search.hybrid_search", new_callable=AsyncMock) as m:
            m.return_value = []
            result = await search_node(state)
        assert result["tool_errors"] == []


# ── 4.2 search_node / rerank_node 错误透传 ───────────────────

SAMPLE_CHUNKS = [
    {"text": "精通 Python", "score": 0.9, "chunk_index": 0, "section": "专业技能", "source": "dense"},
    {"text": "3年 FastAPI 经验", "score": 0.7, "chunk_index": 1, "section": "工作经历", "source": "sparse"},
]


def _base_search_state(**overrides):
    state = {
        "question": "候选人技术栈", "resume_id": 1,
        "rewritten_query": "候选人的技术栈", "route_decision": "search",
        "chunks": [], "search_round": 0, "trace": {},
    }
    state.update(overrides)
    return state


class TestSearchNodeToolErrors:
    @pytest.mark.asyncio
    async def test_hybrid_search_failure_recorded_not_raised(self):
        """主查询检索抛异常 → tool_errors 被填充，且不向上抛出。"""
        state = _base_search_state()
        with patch(
            "services.agentic_rag.search.hybrid_search",
            new_callable=AsyncMock,
            side_effect=RuntimeError("vector DB timeout"),
        ):
            result = await search_node(state)  # 不应抛异常

        assert len(result["tool_errors"]) == 1
        err = result["tool_errors"][0]
        assert err["tool"] == "hybrid_search"
        assert "vector DB timeout" in err["error"]
        assert result["chunks"] == []  # 无结果，但不会让整条链路崩

    @pytest.mark.asyncio
    async def test_supplement_query_failure_is_partial_degradation(self):
        """补充查询失败但主查询正常 → 主结果保留 + 仅补充查询被记为 tool_error。"""
        state = _base_search_state(supplement_queries=["补充查询A", "补充查询B"])
        main_chunks = SAMPLE_CHUNKS

        def _fake_hybrid(resume_id, q, top_k):
            if q == "候选人的技术栈":
                return main_chunks
            raise RuntimeError("rerank service 503")  # 补充查询失败

        with patch(
            "services.agentic_rag.search.hybrid_search",
            side_effect=_fake_hybrid,
        ):
            result = await search_node(state)

        # 主查询结果保留
        assert len(result["chunks"]) == 2
        # 两个补充查询失败都被记录
        assert len(result["tool_errors"]) == 2
        assert all(e["tool"] == "hybrid_search" for e in result["tool_errors"])

    @pytest.mark.asyncio
    async def test_success_path_has_no_tool_errors(self):
        """正常检索成功 → tool_errors 应为空，行为不变。"""
        state = _base_search_state()
        with patch(
            "services.agentic_rag.search.hybrid_search",
            new_callable=AsyncMock,
            return_value=SAMPLE_CHUNKS,
        ):
            result = await search_node(state)
        assert result["tool_errors"] == []
        assert len(result["chunks"]) == 2


class TestRerankNodeToolErrors:
    @pytest.mark.asyncio
    async def test_rerank_failure_recorded_and_falls_back(self):
        """rerank 抛异常 → 记录 tool_error 并降级为原始顺序，不抛出。"""
        state = _base_search_state(chunks=SAMPLE_CHUNKS)
        with patch(
            "services.agentic_rag.search.rerank",
            new_callable=AsyncMock,
            side_effect=ConnectionError("rerank endpoint unreachable"),
        ):
            result = await rerank_node(state)

        assert len(result["tool_errors"]) == 1
        assert result["tool_errors"][0]["tool"] == "rerank"
        # 降级：原样返回 chunks（不重排），保证下游仍有内容可用
        assert result["chunks"] == SAMPLE_CHUNKS

    @pytest.mark.asyncio
    async def test_rerank_success_keeps_tool_errors_from_search(self):
        """rerank 成功时，应继承 search_node 已写入的 tool_errors（累加不覆盖）。"""
        state = _base_search_state(
            chunks=SAMPLE_CHUNKS,
            tool_errors=[{"tool": "hybrid_search", "query": "x", "error": "boom"}],
        )
        with patch(
            "services.agentic_rag.search.rerank",
            new_callable=AsyncMock,
            return_value=SAMPLE_CHUNKS[:1],
        ):
            result = await rerank_node(state)
        # 既有 search 的 error 保留，rerank 未新增
        assert len(result["tool_errors"]) == 1
        assert result["tool_errors"][0]["tool"] == "hybrid_search"


# ── 4.3 generate_node 降级 prompt 注入 ───────────────────────

def _base_generate_state(**overrides):
    base = {
        "question": "候选人技能", "resume_id": 1,
        "rewritten_query": "候选人的专业技能", "route_decision": "search",
        "chunks": [
            {"text": "精通 Python、FastAPI", "section": "专业技能", "chunk_index": 0, "rerank_score": 0.9},
        ],
        "search_round": 1, "answer": "", "sources": [], "trace": {},
        "tool_errors": [],
    }
    base.update(overrides)
    return base


class TestGenerateDegradationPrompt:
    @pytest.mark.asyncio
    async def test_prompt_injects_degradation_note_when_tool_errors(self):
        """tool_errors 非空 → 传给 LLM 的 prompt 包含降级说明，且不伪造来源。"""
        state = _base_generate_state(
            tool_errors=[{"tool": "hybrid_search", "query": "候选人的技能", "error": "vector DB timeout"}],
        )
        captured = {}

        async def _fake_llm(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return "基于已有信息，候选人精通 Python。"

        with patch("services.agentic_rag.generate.llm_generate", side_effect=_fake_llm):
            result = await generate_node(state)

        assert "检索降级提示" in captured["system"]
        assert "vector DB timeout" in captured["system"]  # 具体失败被列出
        assert "不完整" in captured["system"]
        assert "编造" in captured["system"]  # 严禁伪造来源
        assert "部分失败" in captured["user"]
        assert "候选人精通 Python" in result["answer"]

    @pytest.mark.asyncio
    async def test_prompt_clean_when_no_tool_errors(self):
        """无失败时 prompt 不应包含降级说明（保持原行为）。"""
        state = _base_generate_state()
        captured = {}

        async def _fake_llm(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return "候选人精通 Python。"

        with patch("services.agentic_rag.generate.llm_generate", side_effect=_fake_llm):
            await generate_node(state)

        assert "检索降级提示" not in captured["system"]
        assert "编造" not in captured["system"]


# ── 4.4 qa API degraded 标记 ─────────────────────────────────

@pytest.mark.asyncio
async def test_ask_degraded_true_when_tool_errors(client, auth_headers):
    """tool_errors 非空 → AnswerResponse.degraded == True。"""
    from api import qa as qa_module

    fake_record = SimpleNamespace(
        id=1, question="候选人技能", answer="基于已有信息，候选人精通 Python。",
        sources=[{"text": "精通 Python、FastAPI", "section": "专业技能", "chunk_index": 0}],
        created_at="2026-01-01T00:00:00",
    )

    with patch.object(qa_module, "_run_agentic_rag", new_callable=AsyncMock,
                      return_value=("答案", [{"text": "x", "section": "技能", "chunk_index": 0}],
                                    [{"tool": "hybrid_search", "error": "boom"}])), \
         patch("services.resume_service.get_resume", new_callable=AsyncMock), \
         patch.object(qa_module.qa_service, "save_qa", new_callable=AsyncMock, return_value=fake_record):
        resp = await client.post("/api/v1/qa/ask", json={
            "resume_id": 1, "question": "候选人的技能",
        }, headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["degraded"] is True
    # 其余字段仍正常
    assert body["answer"] == fake_record.answer


@pytest.mark.asyncio
async def test_ask_degraded_false_when_no_tool_errors(client, auth_headers):
    """无失败 → AnswerResponse.degraded == False。"""
    from api import qa as qa_module

    fake_record = SimpleNamespace(
        id=2, question="候选人技能", answer="候选人精通 Python。",
        sources=[{"text": "精通 Python", "section": "专业技能", "chunk_index": 0}],
        created_at="2026-01-01T00:00:00",
    )

    with patch.object(qa_module, "_run_agentic_rag", new_callable=AsyncMock,
                      return_value=("答案", [{"text": "x", "section": "技能", "chunk_index": 0}], [])), \
         patch("services.resume_service.get_resume", new_callable=AsyncMock), \
         patch.object(qa_module.qa_service, "save_qa", new_callable=AsyncMock, return_value=fake_record):
        resp = await client.post("/api/v1/qa/ask", json={
            "resume_id": 1, "question": "候选人的技能",
        }, headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["degraded"] is False
