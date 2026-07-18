"""
MCP Server 测试：认证中间件 + Tool/Resource 单元测试。
"""
import json

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock

from mcp_server.server import _current_user_id, get_current_user_id
from main import app


# ── contextvar 测试 ─────────────────────────────────────────


class TestContextVar:
    """测试 get_current_user_id 的 contextvar 行为。"""

    def test_get_set_reset(self):
        """设置后读取，重置后恢复。"""
        token = _current_user_id.set(42)
        assert get_current_user_id() == 42
        _current_user_id.reset(token)
        with pytest.raises(LookupError):
            get_current_user_id()

    def test_nested_contexts(self):
        """嵌套 contextvar 隔离。"""
        outer = _current_user_id.set(1)
        assert get_current_user_id() == 1

        inner = _current_user_id.set(2)
        assert get_current_user_id() == 2

        _current_user_id.reset(inner)
        assert get_current_user_id() == 1
        _current_user_id.reset(outer)


# ── MCP Server 初始化测试 ──────────────────────────────────


class TestMCPServerInit:
    """测试 MCP Server 注册和配置。"""

    def test_tools_registered(self):
        """所有工具已注册。"""
        import asyncio
        from mcp_server.server import mcp, _register_handlers

        _register_handlers()  # 确保注册
        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        assert "search_knowledge_base" in tool_names
        assert "analyze_resume" in tool_names
        assert "rewrite_query" in tool_names

    def test_resources_registered(self):
        """所有资源已注册。"""
        import asyncio
        from mcp_server.server import mcp, _register_handlers

        _register_handlers()
        resources = asyncio.run(mcp.list_resources())
        resource_uris = {str(r.uri) for r in resources}
        assert "resume://list" in resource_uris

    def test_resource_templates_registered(self):
        """资源模板已注册。"""
        import asyncio
        from mcp_server.server import mcp, _register_handlers

        _register_handlers()
        templates = asyncio.run(mcp.list_resource_templates())
        template_uris = {str(t.uriTemplate) for t in templates}
        assert "qa_history://{resume_id}" in template_uris

    def test_app_created(self):
        """ASGI 应用创建成功。"""
        from mcp_server.transport.http import get_mcp_app

        mcp_app = get_mcp_app()
        assert mcp_app is not None
        assert hasattr(mcp_app, "__call__")


# ── 认证中间件 HTTP 测试 ────────────────────────────────────

# MCP 子应用挂载在 /mcp，请求时使用 follow_redirects=False 避免307


@pytest.mark.asyncio
async def test_mcp_no_auth_returns_401():
    """无 Authorization header → 401。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           follow_redirects=False) as client:
        resp = await client.post(
            "/mcp/",
            content=b'{"jsonrpc":"2.0","method":"tools/list","id":1}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert "error" in data


@pytest.mark.asyncio
async def test_mcp_invalid_token_returns_401():
    """无效 token → 401。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           follow_redirects=False) as client:
        resp = await client.post(
            "/mcp/",
            content=b'{"jsonrpc":"2.0","method":"tools/list","id":1}',
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer invalid_token",
            },
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_initialize():
    """initialize 请求 → 200 + MCP 响应（需要 auth token + session manager 启动）。"""
    from core.security import create_access_token
    from mcp_server.server import mcp as mcp_instance

    token = create_access_token({"sub": "1"})

    # 必须先调 streamable_http_app() 触发 session manager 创建
    mcp_instance.streamable_http_app()

    async with mcp_instance.session_manager.run():
        class _MCPTestASGI:
            def __init__(self, sm):
                self._sm = sm

            async def __call__(self, scope, receive, send):
                await self._sm.handle_request(scope, receive, send)

        from starlette.applications import Starlette
        from starlette.routing import Mount

        test_app = Starlette(
            routes=[Mount("/mcp", app=_MCPTestASGI(mcp_instance.session_manager))],
        )

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://localhost:8000",
                               follow_redirects=False) as client:
            resp = await client.post(
                "/mcp/",
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0.1"},
                    },
                }).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Authorization": f"Bearer {token}",
                },
            )
            assert resp.status_code == 200
            # MCP Streamable HTTP 返回 SSE 格式，检查内容是否包含 JSON-RPC 响应
            body = resp.text
            assert "jsonrpc" in body
            assert "result" in body


# ── rewrite_query 工具测试 ─────────────────────────────────


@pytest.mark.asyncio
async def test_rewrite_query_tool():
    """rewrite_query：正常改写。"""
    from mcp_server.tools.rewrite import rewrite_query
    from mcp_server.server import _current_user_id

    mock_rewritten = "候选人掌握的编程语言和技能有哪些"

    token = _current_user_id.set(1)
    try:
        with patch("services.rag.pipeline.rewrite_query", new_callable=AsyncMock) as mock_rw:
            mock_rw.return_value = mock_rewritten
            result = await rewrite_query("除了 Python 还会什么")

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["original"] == "除了 Python 还会什么"
        assert data["rewritten"] == mock_rewritten
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_rewrite_query_tool_empty_input():
    """rewrite_query：空输入 → 错误。"""
    from mcp_server.tools.rewrite import rewrite_query

    result = await rewrite_query("")
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_rewrite_query_tool_fallback():
    """rewrite_query：LLM 失败 → 返回原问题。"""
    from mcp_server.tools.rewrite import rewrite_query
    from mcp_server.server import _current_user_id

    token = _current_user_id.set(1)
    try:
        with patch("services.rag.pipeline.rewrite_query", new_callable=AsyncMock) as mock_rw:
            mock_rw.side_effect = RuntimeError("LLM timeout")
            result = await rewrite_query("测试问题")

        data = json.loads(result[0].text)
        assert data["original"] == "测试问题"
        assert data["rewritten"] == "测试问题"  # 降级返回原问题
        assert "error" in data
    finally:
        _current_user_id.reset(token)


# ── search_knowledge_base 工具测试 ──────────────────────────


@pytest.mark.asyncio
async def test_search_invalid_resume_id():
    """search_knowledge_base：无效 resume_id → 错误。"""
    from mcp_server.tools.search import search_knowledge_base

    token = _current_user_id.set(1)
    try:
        result = await search_knowledge_base(query="test", resume_id="abc")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Invalid resume_id" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_search_resume_not_found():
    """search_knowledge_base：简历不存在 → 错误。"""
    from mcp_server.tools.search import search_knowledge_base

    token = _current_user_id.set(1)
    try:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("core.database.AsyncSessionLocal", return_value=mock_cm):
            result = await search_knowledge_base(query="test", resume_id="999")
            data = json.loads(result[0].text)
            assert "error" in data
            assert "not found" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_search_resume_not_ready():
    """search_knowledge_base：简历未就绪 → 错误。"""
    from mcp_server.tools.search import search_knowledge_base

    token = _current_user_id.set(1)
    try:
        mock_resume = MagicMock()
        mock_resume.status = "processing"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_resume
        mock_db.execute.return_value = mock_result

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("core.database.AsyncSessionLocal", return_value=mock_cm):
            result = await search_knowledge_base(query="test", resume_id="1")
            data = json.loads(result[0].text)
            assert "error" in data
            assert "not ready" in data["error"]
    finally:
        _current_user_id.reset(token)


# ── analyze_resume 工具测试 ─────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_invalid_type():
    """analyze_resume：无效 analysis_type → 错误。"""
    from mcp_server.tools.analyze import analyze_resume

    token = _current_user_id.set(1)
    try:
        result = await analyze_resume(resume_id="1", analysis_type="invalid_type")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Invalid analysis_type" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_analyze_invalid_id():
    """analyze_resume：无效 resume_id → 错误。"""
    from mcp_server.tools.analyze import analyze_resume

    token = _current_user_id.set(1)
    try:
        result = await analyze_resume(resume_id="abc", analysis_type="summary")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Invalid resume_id" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_analyze_resume_not_found():
    """analyze_resume：简历不存在 → 错误。"""
    from mcp_server.tools.analyze import analyze_resume

    token = _current_user_id.set(1)
    try:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("core.database.AsyncSessionLocal", return_value=mock_cm):
            result = await analyze_resume(resume_id="999", analysis_type="summary")
            data = json.loads(result[0].text)
            assert "error" in data
    finally:
        _current_user_id.reset(token)


# ── Resource 测试 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_resume_list_empty():
    """resume_list：无简历 → 空列表。"""
    from mcp_server.resources.resumes import get_resume_list

    token = _current_user_id.set(1)
    try:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("core.database.AsyncSessionLocal", return_value=mock_cm):
            result = await get_resume_list()
            data = json.loads(result)
            assert data == []
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_resume_list_with_data():
    """resume_list：有简历 → 返回列表。"""
    from mcp_server.resources.resumes import get_resume_list

    mock_resume = MagicMock()
    mock_resume.id = 1
    mock_resume.filename = "test.pdf"
    mock_resume.status = "ready"
    mock_resume.chunk_count = 10
    mock_resume.created_at.isoformat.return_value = "2026-01-01T00:00:00"

    token = _current_user_id.set(1)
    try:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_resume]
        mock_db.execute.return_value = mock_result

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("core.database.AsyncSessionLocal", return_value=mock_cm):
            result = await get_resume_list()
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["id"] == 1
            assert data[0]["filename"] == "test.pdf"
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_qa_history_invalid_id():
    """qa_history：无效 resume_id → 错误。"""
    from mcp_server.resources.history import get_qa_history

    token = _current_user_id.set(1)
    try:
        result = await get_qa_history("abc")
        data = json.loads(result)
        assert "error" in data
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_qa_history_not_found():
    """qa_history：简历不存在 → 错误。"""
    from mcp_server.resources.history import get_qa_history

    token = _current_user_id.set(1)
    try:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("core.database.AsyncSessionLocal", return_value=mock_cm):
            result = await get_qa_history("999")
            data = json.loads(result)
            assert "error" in data
    finally:
        _current_user_id.reset(token)
