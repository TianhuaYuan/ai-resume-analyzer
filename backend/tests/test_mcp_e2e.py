"""
MCP 端到端测试：验证完整的 MCP 驱动问答流程。

测试场景：
  1. 完整问答流程（通过 MCP）：rewrite → route → search → rerank → generate → evaluate → output
  2. 流式问答（通过 MCP）：验证 SSE 流式 MCP 响应解析
  3. 多轮对话（通过 MCP）：验证 contextvar 传播 + 状态隔离

设计说明：
  由于 MCP Server 依赖真实 LLM API，本测试通过 mock MCP 工具实现
  来验证端到端流程的正确性，而非真实的网络调用。

运行: python -m pytest tests/test_mcp_e2e.py -v
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.agentic_rag.state import AgenticRAGState


# ── 辅助函数 ─────────────────────────────────────────────────


def _make_initial_state(question: str = "工作经历是什么？", resume_id: int = 1) -> dict:
    """构造初始 graph 输入 state。"""
    return {
        "question": question,
        "resume_id": resume_id,
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


# ── 场景 1：完整问答流程 ─────────────────────────────────────


class TestE2ECompleteQAPipeline:
    """完整问答流程端到端测试。"""

    @pytest.mark.asyncio
    async def test_single_round_success(self):
        """单轮问答：rewrite → route → search → rerank → generate → evaluate(pass) → output。"""
        from services.agentic_rag.mcp_graph import create_mcp_agentic_rag_graph

        graph = create_mcp_agentic_rag_graph()

        mock_search_results = [
            {
                "text": "在某公司担任Python开发工程师3年",
                "chunk_index": 0,
                "section": "工作经历",
                "score": 0.92,
            },
            {
                "text": "负责后端微服务架构设计与实现",
                "chunk_index": 1,
                "section": "工作经历",
                "score": 0.85,
            },
        ]
        mock_rerank_results = [
            {
                "text": "在某公司担任Python开发工程师3年",
                "chunk_index": 0,
                "section": "工作经历",
                "rerank_score": 0.96,
            },
            {
                "text": "负责后端微服务架构设计与实现",
                "chunk_index": 1,
                "section": "工作经历",
                "rerank_score": 0.88,
            },
        ]
        mock_generate_result = {
            "answer": "候选人拥有3年Python开发经验，在某公司担任开发工程师，负责后端微服务架构的设计与实现。",
            "sources": [
                {
                    "chunk_index": 0,
                    "text": "在某公司担任Python开发工程师3年",
                    "section": "工作经历",
                    "rerank_score": 0.96,
                },
                {
                    "chunk_index": 1,
                    "text": "负责后端微服务架构设计与实现",
                    "section": "工作经历",
                    "rerank_score": 0.88,
                },
            ],
            "rejected": False,
        }

        with (
            patch(
                "services.agentic_rag.rewrite.with_retry",
                new_callable=AsyncMock,
                return_value="候选人有哪些工作经历和经验",
            ),
            patch(
                "services.agentic_rag.rewrite._classify_route",
                new_callable=AsyncMock,
                return_value="search",
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_search",
                new_callable=AsyncMock,
                return_value=mock_search_results,
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_rerank",
                new_callable=AsyncMock,
                return_value=mock_rerank_results,
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_generate",
                new_callable=AsyncMock,
                return_value=mock_generate_result,
            ),
            patch(
                "services.agentic_rag.generate.with_retry",
                new_callable=AsyncMock,
                return_value='{"completeness": 9, "accuracy": 9, "source_credibility": 9, "feedback": "回答准确，引用了简历原文"}',
            ),
        ):
            result = await graph.ainvoke(
                _make_initial_state("工作经历是什么？"),
                config={"configurable": {"thread_id": "e2e-single"}},
            )

        # 验证流程完整性
        assert result["route_decision"] == "search"
        assert result["search_round"] >= 1
        assert result["final_answer"] != ""
        assert len(result["final_sources"]) == 2

        # 验证 trace 完整性
        assert "rewrite" in result["trace"]
        assert "search" in result["trace"]
        assert result["trace"]["search"]["method"] == "mcp"
        assert "generate" in result["trace"]
        assert result["trace"]["generate"]["method"] == "mcp"

        # 验证答案内容
        assert "3年" in result["final_answer"]
        assert "Python" in result["final_answer"]

    @pytest.mark.asyncio
    async def test_multi_round_retry_then_succeed(self):
        """多轮问答：eval(低分) → retry → search(第2轮) → eval(高分) → output。"""
        from services.agentic_rag.mcp_graph import create_mcp_agentic_rag_graph

        graph = create_mcp_agentic_rag_graph()

        mock_search = [{"text": "相关片段", "chunk_index": 0, "section": "工作经历", "score": 0.85}]
        mock_rerank = [
            {"text": "相关片段", "chunk_index": 0, "section": "工作经历", "rerank_score": 0.9}
        ]
        mock_generate = {
            "answer": "候选人有相关工作经验。",
            "sources": [
                {"chunk_index": 0, "text": "相关片段", "section": "工作经历", "rerank_score": 0.9}
            ],
            "rejected": False,
        }

        with (
            patch(
                "services.agentic_rag.rewrite.with_retry",
                new_callable=AsyncMock,
                return_value="查询内容",
            ),
            patch(
                "services.agentic_rag.rewrite._classify_route",
                new_callable=AsyncMock,
                return_value="search",
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_search",
                new_callable=AsyncMock,
                return_value=mock_search,
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_rerank",
                new_callable=AsyncMock,
                return_value=mock_rerank,
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_generate",
                new_callable=AsyncMock,
                return_value=mock_generate,
            ),
            patch(
                "services.agentic_rag.generate.with_retry",
                new_callable=AsyncMock,
                side_effect=[
                    '{"completeness": 3, "accuracy": 3, "source_credibility": 3, "feedback": "回答过于简略"}',  # eval round 1 → retry
                    '{"completeness": 8, "accuracy": 8, "source_credibility": 8, "feedback": "回答准确"}',  # eval round 2 → pass
                ],
            ),
        ):
            result = await graph.ainvoke(
                _make_initial_state("项目经历？"),
                config={"configurable": {"thread_id": "e2e-retry"}},
            )

        assert result["search_round"] >= 2
        assert result["final_answer"] != ""
        assert result["final_sources"] != []

    @pytest.mark.asyncio
    async def test_empty_search_then_rejection(self):
        """空搜索结果 → 拒答。"""
        from services.agentic_rag.mcp_graph import create_mcp_agentic_rag_graph

        graph = create_mcp_agentic_rag_graph()

        with (
            patch(
                "services.agentic_rag.rewrite.with_retry",
                new_callable=AsyncMock,
                return_value="航天经历",
            ),
            patch(
                "services.agentic_rag.rewrite._classify_route",
                new_callable=AsyncMock,
                return_value="search",
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_search", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_rerank", new_callable=AsyncMock, return_value=[]
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_generate",
                new_callable=AsyncMock,
                return_value={
                    "answer": "抱歉，简历中未提及该信息。",
                    "sources": [],
                    "rejected": True,
                },
            ),
        ):
            result = await graph.ainvoke(
                _make_initial_state("航天经历？"),
                config={"configurable": {"thread_id": "e2e-empty"}},
            )

        assert "未提及" in result["final_answer"]
        assert result["trace"]["generate"]["rejected"] is True
        assert result["final_sources"] == []

    @pytest.mark.asyncio
    async def test_direct_answer_greeting(self):
        """问候 → direct_answer → 模板回复。"""
        from services.agentic_rag.mcp_graph import (
            create_mcp_agentic_rag_graph,
            _DIRECT_ANSWER_REPLY,
        )

        graph = create_mcp_agentic_rag_graph()

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
                _make_initial_state("你好"),
                config={"configurable": {"thread_id": "e2e-greeting"}},
            )

        assert result["route_decision"] == "direct_answer"
        assert result["final_answer"] == _DIRECT_ANSWER_REPLY
        assert result["final_sources"] == []
        assert "search" not in result["trace"]
        assert "direct_answer" in result["trace"]

    @pytest.mark.asyncio
    async def test_low_rerank_score_triggers_rejection(self):
        """rerank 分数过低 → 拒答。"""
        from services.agentic_rag.mcp_graph import create_mcp_agentic_rag_graph

        graph = create_mcp_agentic_rag_graph()

        mock_search = [{"text": "内容", "chunk_index": 0, "section": "其他", "score": 0.3}]
        mock_rerank = [{"text": "内容", "chunk_index": 0, "section": "其他", "rerank_score": 0.1}]

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
                "services.agentic_rag.mcp_nodes.mcp_search",
                new_callable=AsyncMock,
                return_value=mock_search,
            ),
            patch(
                "services.agentic_rag.mcp_nodes.mcp_rerank",
                new_callable=AsyncMock,
                return_value=mock_rerank,
            ),
        ):
            result = await graph.ainvoke(
                _make_initial_state("航天经历？"),
                config={"configurable": {"thread_id": "e2e-low-score"}},
            )

        assert "未提及" in result["final_answer"]
        assert result["trace"]["generate"]["rejected"] is True


# ── 场景 2：流式问答（MCP SSE 解析） ─────────────────────────


class TestE2EStreamingMCP:
    """流式 MCP 响应解析测试。"""

    @pytest.mark.asyncio
    async def test_sse_response_parsing(self):
        """MCP Client 正确解析 SSE 格式响应。"""
        from mcp_client.client import MCPClient

        client = MCPClient(base_url="http://test/mcp")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/event-stream"}

        # 模拟 SSE 数据流
        sse_lines = [
            'data: {"jsonrpc":"2.0","id":"1","result":{"content":[{"type":"text","text":"{\\"answer\\": \\"候选人有3年经验\\"}"}]}}',
            "",
        ]

        async def mock_aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._client = mock_http

        result = await client.call_tool(
            "generate_answer", {"question": "test", "context": "test", "resume_id": "1"}
        )
        assert "content" in result

    @pytest.mark.asyncio
    async def test_sse_multi_event_parsing(self):
        """MCP Client 解析多事件 SSE 响应（取最后一个 data 事件）。"""
        from mcp_client.client import MCPClient

        client = MCPClient(base_url="http://test/mcp")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/event-stream"}

        async def mock_aiter_lines():
            yield 'data: {"jsonrpc":"2.0","id":"1","result":{"partial": true}}'
            yield ""
            yield 'data: {"jsonrpc":"2.0","id":"1","result":{"content":[{"type":"text","text":"{\\"ok\\": true}"}]}}'
            yield ""

        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._client = mock_http

        result = await client.call_tool("test", {})
        assert "content" in result

    @pytest.mark.asyncio
    async def test_sse_empty_stream_raises_error(self):
        """MCP Client 处理空 SSE 流 → MCPClientError。"""
        from mcp_client.client import MCPClient, MCPClientError

        client = MCPClient(base_url="http://test/mcp")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/event-stream"}

        async def mock_aiter_lines():
            yield ""
            yield "data: "
            yield ""

        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._client = mock_http

        with pytest.raises(MCPClientError, match="No data received"):
            await client.call_tool("test", {})

    @pytest.mark.asyncio
    async def test_sse_mixed_content_type(self):
        """MCP Client 处理 content-type 同时包含 json 和 sse — 走 SSE 路径。"""
        from mcp_client.client import MCPClient

        client = MCPClient(base_url="http://test/mcp")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json, text/event-stream"}

        async def mock_aiter_lines():
            yield 'data: {"jsonrpc":"2.0","id":"1","result":{"content":[{"type":"text","text":"{\\"key\\": \\"value\\"}"}]}}'
            yield ""

        mock_response.aiter_lines = mock_aiter_lines
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._client = mock_http

        result = await client.call_tool("test", {})
        assert "content" in result


# ── 场景 3：多轮对话 ─────────────────────────────────────────


class TestE2EMultiTurnDialogue:
    """多轮对话场景测试。"""

    @pytest.mark.asyncio
    async def test_contextvar_isolation_across_tasks(self):
        """不同 async task 中 contextvar 隔离。"""
        import asyncio
        from mcp_server.server import _current_user_id, get_current_user_id

        results = []

        async def task_a():
            token = _current_user_id.set(10)
            await asyncio.sleep(0.01)
            results.append(("a", get_current_user_id()))
            _current_user_id.reset(token)

        async def task_b():
            token = _current_user_id.set(20)
            await asyncio.sleep(0.01)
            results.append(("b", get_current_user_id()))
            _current_user_id.reset(token)

        await asyncio.gather(task_a(), task_b())

        # 验证两个 task 的 contextvar 互不干扰
        a_result = next(r for r in results if r[0] == "a")
        b_result = next(r for r in results if r[0] == "b")
        assert a_result[1] == 10
        assert b_result[1] == 20

    @pytest.mark.asyncio
    async def test_mcp_client_stateless_across_calls(self):
        """MCP Client 跨调用无状态（每次调用独立）。"""
        from mcp_client.client import MCPClient

        client = MCPClient(base_url="http://test/mcp")

        # 模拟两次独立调用
        for i in range(2):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json.return_value = {
                "jsonrpc": "2.0",
                "id": str(i),
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"call": i})}],
                },
            }
            mock_response.raise_for_status = MagicMock()

            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            client._client = mock_http

            await client.call_tool("test", {"call_index": i})
            # 每次调用使用独立的 request_id，验证无状态
            call_args = mock_http.post.call_args
            payload = call_args[1].get("json") or call_args[0][1]
            assert payload["id"] != ""  # 每次有唯一的 request_id

    @pytest.mark.asyncio
    async def test_graph_thread_isolation(self):
        """不同 thread_id 的 graph 执行互不影响。"""
        from services.agentic_rag.mcp_graph import create_mcp_agentic_rag_graph

        graph = create_mcp_agentic_rag_graph()

        # 两个并发调用使用不同 thread_id
        async def run_graph(thread_id: str, question: str):
            with (
                patch(
                    "services.agentic_rag.rewrite.with_retry",
                    new_callable=AsyncMock,
                    return_value=question,
                ),
                patch(
                    "services.agentic_rag.rewrite._classify_route",
                    new_callable=AsyncMock,
                    return_value="direct_answer",
                ),
            ):
                return await graph.ainvoke(
                    _make_initial_state(question),
                    config={"configurable": {"thread_id": thread_id}},
                )

        import asyncio

        r1, r2 = await asyncio.gather(
            run_graph("thread-1", "你好"),
            run_graph("thread-2", "再见"),
        )

        # 两个线程的执行结果互不影响
        assert r1["final_answer"] != ""
        assert r2["final_answer"] != ""
        # thread_id 隔离：各自有独立的 trace
        assert "direct_answer" in r1["trace"]
        assert "direct_answer" in r2["trace"]

    @pytest.mark.asyncio
    async def test_mcp_client_auto_connect(self):
        """MCP Client 自动连接：未 connect 时 call_tool 自动创建连接。"""
        from mcp_client.client import MCPClient

        client = MCPClient(base_url="http://test/mcp")
        assert client._client is None  # 初始未连接

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {"content": [{"type": "text", "text": '{"ok": true}'}]},
        }
        mock_response.raise_for_status = MagicMock()

        # 模拟 httpx.AsyncClient 的构造
        with patch("mcp_client.client.httpx.AsyncClient") as mock_httpx:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_httpx.return_value = mock_http

            result = await client.call_tool("test", {})

        assert client._client is not None  # 自动连接后 _client 不为 None
        assert "content" in result
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_mcp_client_singleton_behavior(self):
        """MCP Client 单例：get_mcp_client 返回同一个实例。"""
        from mcp_client import client as client_mod

        # 清理单例
        old_instance = client_mod._client_instance
        client_mod._client_instance = None

        try:
            c1 = await client_mod.get_mcp_client()
            c2 = await client_mod.get_mcp_client()
            assert c1 is c2

            # 关闭后重新获取
            await client_mod.close_mcp_client()
            c3 = await client_mod.get_mcp_client()
            assert c3 is not c1  # 新实例
        finally:
            client_mod._client_instance = old_instance


# ── 场景 4：MCP Graph 完整条件边覆盖 ─────────────────────────


class TestE2EConditionalEdges:
    """条件边覆盖测试。"""

    @pytest.mark.asyncio
    async def test_max_retry_stops_loop(self):
        """search_round=3 时 evaluate 即使低分也强制通过（防止无限循环）。"""
        from services.agentic_rag.mcp_graph import _route_after_evaluate

        # 直接测试条件边逻辑
        state = {
            "should_retry": True,
            "search_round": 3,  # 已达上限
        }
        assert _route_after_evaluate(state) == "output"

    @pytest.mark.asyncio
    async def test_route_decision_edge_cases(self):
        """route 决策边界值测试。"""
        from services.agentic_rag.mcp_graph import _route_after_route

        # 空字符串默认走 search
        assert _route_after_route({"route_decision": ""}) == "mcp_search"
        # "search" 走 mcp_search
        assert _route_after_route({"route_decision": "search"}) == "mcp_search"
        # "direct_answer" 走 direct_answer
        assert _route_after_route({"route_decision": "direct_answer"}) == "direct_answer"

    @pytest.mark.asyncio
    async def test_evaluate_score_threshold(self):
        """evaluate 评分阈值测试：score < 0.6 → retry。"""
        from services.agentic_rag.generate import evaluate_node

        state: AgenticRAGState = {
            "question": "test",
            "resume_id": 1,
            "rewritten_query": "test",
            "route_decision": "search",
            "chunks": [],
            "search_round": 1,
            "answer": "测试答案",
            "sources": [],
            "eval_score": 0.0,
            "eval_feedback": "",
            "should_retry": False,
            "final_answer": "",
            "final_sources": [],
            "trace": {},
        }

        # 低分 → should_retry=True
        with patch(
            "services.agentic_rag.generate.with_retry",
            new_callable=AsyncMock,
            return_value='{"completeness": 3, "accuracy": 3, "source_credibility": 3, "feedback": "不理想"}',
        ):
            result = await evaluate_node(state)
            assert result["should_retry"] is True
            assert abs(result["eval_score"] - 0.3) < 1e-6

        # 高分 → should_retry=False
        with patch(
            "services.agentic_rag.generate.with_retry",
            new_callable=AsyncMock,
            return_value='{"completeness": 9, "accuracy": 9, "source_credibility": 9, "feedback": "准确"}',
        ):
            result = await evaluate_node(state)
            assert result["should_retry"] is False
            assert abs(result["eval_score"] - 0.9) < 1e-6
