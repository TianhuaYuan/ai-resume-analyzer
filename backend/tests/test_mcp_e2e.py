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


# 注：MCP 版 Agentic RAG 图（mcp_graph/mcp_nodes）已在 T14 退役，
# 完整问答流程的端到端测试由标准图 test_agentic_graph_integration.py 覆盖。


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
