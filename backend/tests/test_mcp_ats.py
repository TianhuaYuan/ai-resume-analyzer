"""
MCP P2-D 测试：ats_audit 和 match_job_description 工具。

仿 test_mcp_server.py 模式：
- 认证缺失 → error JSON
- mock 服务成功 → JSON 含结构化数据
- mock 服务异常 → error JSON
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_server.server import _current_user_id


# ═══════════════════════════════════════════════════════════
# ats_audit 工具测试
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ats_audit_no_auth():
    """ats_audit：无用户上下文 → error JSON。"""
    from mcp_server.tools.ats import ats_audit

    result = await ats_audit(resume_id="1")
    data = json.loads(result[0].text)
    assert "error" in data
    assert "authentication required" in data["error"]


@pytest.mark.asyncio
async def test_ats_audit_invalid_id():
    """ats_audit：无效 resume_id → error JSON。"""
    from mcp_server.tools.ats import ats_audit

    token = _current_user_id.set(1)
    try:
        result = await ats_audit(resume_id="abc")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Invalid resume_id" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_ats_audit_success():
    """ats_audit：正常审计 → JSON 含 ats_score + issues。"""
    from mcp_server.tools.ats import ats_audit

    mock_response = MagicMock()
    mock_response.model_dump_json.return_value = json.dumps(
        {
            "resume_id": 1,
            "ats_score": 80,
            "issue_count": 2,
            "issues": [
                {"section": "教育背景", "issue_type": "special_symbol", "severity": "medium"}
            ],
            "method": "html",
            "pdf_available": False,
            "warnings": [],
        },
        ensure_ascii=False,
    )

    token = _current_user_id.set(1)
    try:
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.tools.ats.AsyncSessionLocal", return_value=mock_cm), patch(
            "services.ats_audit_service.audit_resume", new_callable=AsyncMock
        ) as mock_audit:
            mock_audit.return_value = mock_response
            result = await ats_audit(resume_id="1")

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["resume_id"] == 1
        assert data["ats_score"] == 80
        assert data["issue_count"] == 2
        assert len(data["issues"]) == 1
        assert data["method"] == "html"
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_ats_audit_not_found():
    """ats_audit：简历不存在 → error JSON（服务抛 HTTPException）。"""
    from mcp_server.tools.ats import ats_audit
    from fastapi import HTTPException

    token = _current_user_id.set(1)
    try:
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.tools.ats.AsyncSessionLocal", return_value=mock_cm), patch(
            "services.ats_audit_service.audit_resume", new_callable=AsyncMock
        ) as mock_audit:
            mock_audit.side_effect = HTTPException(
                status_code=404, detail="简历不存在或无权访问"
            )
            result = await ats_audit(resume_id="999")

        data = json.loads(result[0].text)
        assert "error" in data
        assert "简历不存在" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_ats_audit_not_ready():
    """ats_audit：简历未就绪 → error JSON（409）。"""
    from mcp_server.tools.ats import ats_audit
    from fastapi import HTTPException

    token = _current_user_id.set(1)
    try:
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.tools.ats.AsyncSessionLocal", return_value=mock_cm), patch(
            "services.ats_audit_service.audit_resume", new_callable=AsyncMock
        ) as mock_audit:
            mock_audit.side_effect = HTTPException(
                status_code=409, detail="简历未就绪（当前状态: processing）"
            )
            result = await ats_audit(resume_id="1")

        data = json.loads(result[0].text)
        assert "error" in data
        assert "未就绪" in data["error"]
    finally:
        _current_user_id.reset(token)


# ═══════════════════════════════════════════════════════════
# match_job_description 工具测试
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_jd_match_no_auth():
    """match_job_description：无用户上下文 → error JSON。"""
    from mcp_server.tools.jd_match import match_job_description

    result = await match_job_description(resume_id="1", jd_text="Python developer")
    data = json.loads(result[0].text)
    assert "error" in data
    assert "authentication required" in data["error"]


@pytest.mark.asyncio
async def test_jd_match_invalid_id():
    """match_job_description：无效 resume_id → error JSON。"""
    from mcp_server.tools.jd_match import match_job_description

    token = _current_user_id.set(1)
    try:
        result = await match_job_description(resume_id="abc", jd_text="Python developer")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "Invalid resume_id" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_jd_match_empty_jd():
    """match_job_description：空 JD 文本 → error JSON。"""
    from mcp_server.tools.jd_match import match_job_description

    token = _current_user_id.set(1)
    try:
        result = await match_job_description(resume_id="1", jd_text="")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "empty" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_jd_match_whitespace_jd():
    """match_job_description：纯空白 JD → error JSON。"""
    from mcp_server.tools.jd_match import match_job_description

    token = _current_user_id.set(1)
    try:
        result = await match_job_description(resume_id="1", jd_text="   \n  ")
        data = json.loads(result[0].text)
        assert "error" in data
        assert "empty" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_jd_match_success_structured():
    """match_job_description：结构化匹配成功 → JSON 含 scores/gaps/matched/missing。"""
    from mcp_server.tools.jd_match import match_job_description

    mock_result = {
        "resume_id": 1,
        "analysis": "匹配度 75 分：匹配 5 项，缺失 2 项",
        "scores": {"overall": 75, "band": "B"},
        "matched_keywords": ["Python", "FastAPI", "Docker", "SQL", "Git"],
        "missing_keywords": ["Kubernetes", "CI/CD"],
        "gaps": ["建议补充容器编排经验", "建议补充 CI/CD 实践经验"],
    }

    token = _current_user_id.set(1)
    try:
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.tools.jd_match.AsyncSessionLocal", return_value=mock_cm), patch(
            "services.match_jd_service.match_jd", new_callable=AsyncMock
        ) as mock_match:
            mock_match.return_value = mock_result
            result = await match_job_description(
                resume_id="1", jd_text="We are looking for a Python developer..."
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["resume_id"] == 1
        assert data["scores"]["overall"] == 75
        assert len(data["matched_keywords"]) == 5
        assert len(data["missing_keywords"]) == 2
        assert len(data["gaps"]) == 2
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_jd_match_success_markdown_fallback():
    """match_job_description：markdown 降级匹配 → JSON 含 analysis 字段。"""
    from mcp_server.tools.jd_match import match_job_description

    mock_result = {
        "resume_id": 1,
        "analysis": "## 匹配分数\n85\n\n## 匹配点\nPython 经验丰富...",
    }

    token = _current_user_id.set(1)
    try:
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.tools.jd_match.AsyncSessionLocal", return_value=mock_cm), patch(
            "services.match_jd_service.match_jd", new_callable=AsyncMock
        ) as mock_match:
            mock_match.return_value = mock_result
            result = await match_job_description(
                resume_id="1", jd_text="Python developer position"
            )

        data = json.loads(result[0].text)
        assert data["resume_id"] == 1
        assert "analysis" in data
        assert "匹配分数" in data["analysis"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_jd_match_not_found():
    """match_job_description：简历不存在 → error JSON（404）。"""
    from mcp_server.tools.jd_match import match_job_description
    from fastapi import HTTPException

    token = _current_user_id.set(1)
    try:
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.tools.jd_match.AsyncSessionLocal", return_value=mock_cm), patch(
            "services.match_jd_service.match_jd", new_callable=AsyncMock
        ) as mock_match:
            mock_match.side_effect = HTTPException(
                status_code=404, detail="简历不存在或无权访问"
            )
            result = await match_job_description(
                resume_id="999", jd_text="Python developer"
            )

        data = json.loads(result[0].text)
        assert "error" in data
        assert "简历不存在" in data["error"]
    finally:
        _current_user_id.reset(token)


@pytest.mark.asyncio
async def test_jd_match_not_ready():
    """match_job_description：简历未就绪 → error JSON（409）。"""
    from mcp_server.tools.jd_match import match_job_description
    from fastapi import HTTPException

    token = _current_user_id.set(1)
    try:
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_server.tools.jd_match.AsyncSessionLocal", return_value=mock_cm), patch(
            "services.match_jd_service.match_jd", new_callable=AsyncMock
        ) as mock_match:
            mock_match.side_effect = HTTPException(
                status_code=409, detail="简历未就绪（当前状态: processing）"
            )
            result = await match_job_description(
                resume_id="1", jd_text="Python developer"
            )

        data = json.loads(result[0].text)
        assert "error" in data
        assert "未就绪" in data["error"]
    finally:
        _current_user_id.reset(token)


# ═══════════════════════════════════════════════════════════
# 注册验证测试
# ═══════════════════════════════════════════════════════════


def test_new_tools_registered():
    """ats_audit 和 match_job_description 已注册到 MCP Server。"""
    import asyncio
    from mcp_server.server import mcp, _register_handlers

    _register_handlers()
    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    assert "ats_audit" in tool_names
    assert "match_job_description" in tool_names
