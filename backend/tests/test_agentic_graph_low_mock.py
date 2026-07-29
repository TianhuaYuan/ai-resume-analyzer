"""P2-11: Agentic Graph E2E 测试 — 降 mock 策略。

与 test_agentic_graph.py 的区别：
- test_agentic_graph.py：mock 每个节点的入口函数（rewrite/generate/evaluate）
- 本文件：只 mock 最底层 LLM client（get_chat_client），走真实的节点业务逻辑

这样能验证：
1. 真实的 prompt 构建逻辑（rewrite 的 system/user prompt 拼装）
2. 真实的 generate 流程（build_prompt → llm_generate → 答案提取）
3. 真实的 evaluate 评分解析（JSON 解析 + 加权计算）
4. 真实的 Reflexion 循环（self_reflection → supplement_search → 二轮检索）

注意：需要 langgraph 安装才能运行。未安装时自动 skip。
"""
import pytest

# langgraph 是前置依赖，未安装时跳过所有测试
pytest.importorskip("langgraph")

from unittest.mock import AsyncMock, patch

from services.agentic_rag.graph import create_agentic_rag_graph


def _make_initial_state(question: str = "工作经历是什么？", resume_id: int = 1) -> dict:
    """构造 Agentic RAG 图的完整初始 state。"""
    return {
        "question": question,
        "resume_id": resume_id,
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
        "reflection_result": "",
        "missing_info": [],
        "supplement_queries": [],
        "reflection_round": 0,
        "final_answer": "",
        "final_sources": [],
        "trace": {},
        "tool_errors": [],
    }


class TestLowMockSearchPath:
    """降 mock：只 mock 底层 LLM client，走真实 rewrite → search → generate → evaluate。"""

    @pytest.mark.asyncio
    async def test_search_path_with_real_node_logic(self):
        """search 路径：真实节点逻辑 + mock 底层 LLM client + mock 检索。"""
        graph = create_agentic_rag_graph()

        # P2-11：LLM 响应序列严格按节点调用顺序：
        # rewrite_query → _classify_route → generate_node → evaluate_node
        def _make_response(content: str):
            resp = AsyncMock()
            resp.choices = [AsyncMock()]
            resp.choices[0].message.content = content
            resp.choices[0].delta = None
            return resp

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[
                _make_response("工作经历"),  # 1. rewrite_query
                _make_response("search"),  # 2. _classify_route
                _make_response("候选人有3年Python开发经验"),  # 3. generate_node
                _make_response(  # 4. evaluate_node（高分通过）
                    '{"completeness": 8, "accuracy": 9, "source_credibility": 7, '
                    '"feedback": "回答准确完整"}'
                ),
            ]
        )

        mock_chunks = [
            {"text": "3年Python开发经验", "chunk_index": 0, "section": "工作经历", "score": 0.9}
        ]
        mock_reranked = [
            {"text": "3年Python开发经验", "chunk_index": 0, "section": "工作经历", "rerank_score": 0.95}
        ]

        # P2-11：get_chat_client 实际由 services.rag.pipeline 导入并调用，
        # agentic_rag 子模块（rewrite/generate/reflection）通过 llm_generate 间接使用，
        # 因此 patch pipeline.get_chat_client 即可覆盖所有节点的 LLM 调用。
        with patch(
            "services.rag.pipeline.get_chat_client", return_value=mock_client
        ), patch(
            "services.agentic_rag.search.hybrid_search",
            new_callable=AsyncMock,
            return_value=mock_chunks,
        ), patch(
            "services.agentic_rag.search.rerank",
            new_callable=AsyncMock,
            return_value=mock_reranked,
        ), patch(
            "services.agentic_rag.generate.reject_if_low_score", return_value=False
        ):
            result = await graph.ainvoke(
                _make_initial_state("工作经历是什么？"),
                config={"configurable": {"thread_id": "low-mock-search"}},
            )

        assert result["route_decision"] == "search"
        assert result["search_round"] >= 1
        assert result["final_answer"] != ""
        assert len(result["final_sources"]) > 0
        assert result["eval_score"] > 0.6


class TestLowMockDirectAnswer:
    """降 mock：direct_answer 路径只 mock LLM client for rewrite。"""

    @pytest.mark.asyncio
    async def test_direct_answer_with_real_rewrite(self):
        """问候 → 真实 rewrite 判定 direct_answer → 模板回复 → output。"""
        graph = create_agentic_rag_graph()

        # rewrite 的 LLM 返回：判定为 direct_answer
        mock_rewrite_response = AsyncMock()
        mock_rewrite_response.choices = [AsyncMock()]
        mock_rewrite_response.choices[0].message.content = "你好"
        mock_rewrite_response.choices[0].delta = None

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=mock_rewrite_response
        )

        # P2-11：pipeline.get_chat_client 覆盖 rewrite 节点的 llm_generate 调用
        with patch(
            "services.rag.pipeline.get_chat_client", return_value=mock_client
        ), patch(
            "services.agentic_rag.rewrite._classify_route",
            new_callable=AsyncMock,
            return_value="direct_answer",
        ):
            result = await graph.ainvoke(
                _make_initial_state("你好"),
                config={"configurable": {"thread_id": "low-mock-direct"}},
            )

        assert result["route_decision"] == "direct_answer"
        assert result["final_answer"] != ""
        assert "direct_answer" in result["trace"]


class TestLowMockReflexion:
    """降 mock：Reflexion 循环，真实 evaluate 评分解析 + 真实 self_reflection。"""

    @pytest.mark.asyncio
    async def test_reflexion_with_real_evaluate_parsing(self):
        """低分 → 真实 self_reflection → 二轮 search → 高分通过 → output。"""
        graph = create_agentic_rag_graph()

        # LLM 响应序列：rewrite, generate_r1, eval_r1(低分), reflection, generate_r2, eval_r2(高分)
        def _make_response(content: str):
            resp = AsyncMock()
            resp.choices = [AsyncMock()]
            resp.choices[0].message.content = content
            resp.choices[0].delta = None
            return resp

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[
                _make_response("工作经历"),  # 1. rewrite_query
                _make_response("search"),  # 2. _classify_route
                _make_response("候选人有3年经验"),  # 3. generate r1
                _make_response(  # 4. eval r1 (低分)
                    '{"completeness": 3, "accuracy": 5, "source_credibility": 3, '
                    '"feedback": "缺少项目细节"}'
                ),
                _make_response(  # 5. self_reflection
                    '{"reflection": "缺少项目经验", "missing_info": ["项目经历"], '
                    '"supplement_queries": ["项目开发经验"]}'
                ),
                _make_response("候选人有3年经验，曾开发电商平台"),  # 6. generate r2
                _make_response(  # 7. eval r2 (高分)
                    '{"completeness": 8, "accuracy": 8, "source_credibility": 7, '
                    '"feedback": "回答准确"}'
                ),
            ]
        )

        mock_chunks = [
            {"text": "3年经验", "chunk_index": 0, "section": "工作", "score": 0.8}
        ]
        mock_reranked = [
            {"text": "3年经验", "chunk_index": 0, "section": "工作", "rerank_score": 0.9}
        ]

        # P2-11：统一 patch pipeline.get_chat_client，覆盖 rewrite/generate/evaluate/reflection 所有 LLM 调用
        with patch(
            "services.rag.pipeline.get_chat_client", return_value=mock_client
        ), patch(
            "services.agentic_rag.search.hybrid_search",
            new_callable=AsyncMock,
            return_value=mock_chunks,
        ), patch(
            "services.agentic_rag.search.rerank",
            new_callable=AsyncMock,
            return_value=mock_reranked,
        ), patch(
            "services.agentic_rag.generate.reject_if_low_score", return_value=False
        ):
            result = await graph.ainvoke(
                _make_initial_state("工作经历？"),
                config={"configurable": {"thread_id": "low-mock-reflexion"}},
            )

        assert result["search_round"] >= 2, "应至少搜索 2 轮"
        assert result["reflection_round"] >= 1, "应至少反思 1 轮"
        assert result["final_answer"] != ""
        assert result["eval_score"] > 0.6, "最终评分应通过阈值"
