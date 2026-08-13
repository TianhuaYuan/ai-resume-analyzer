"""/ask/stream 端点支持 mode=agentic 走 Agentic RAG 图。

原 bug：流式端点只走普通 RAG 流式路径，无法使用 Agentic RAG 的
改写→检索→重排→生成→评估→反思完整管线。
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_stream_agentic_mode_calls_run_agentic_rag(
    client: AsyncClient, auth_headers: dict
):
    """mode=agentic 时应调用 _run_agentic_rag 并返回 SSE 流。"""
    mock_answer = "这是 Agentic RAG 的完整答案"
    mock_sources = [{"text": "来源1", "chunk_index": 0, "section": "edu"}]
    mock_tool_errors: list[dict] = []

    with patch(
        "api.qa.resume_service.get_resume",
        new_callable=AsyncMock,
    ), patch(
        "api.qa._run_agentic_rag",
        new_callable=AsyncMock,
        return_value=(mock_answer, mock_sources, mock_tool_errors),
    ), patch(
        "api.qa.qa_service.save_qa",
        new_callable=AsyncMock,
        return_value=type("R", (), {"id": 42}),
    ):
        resp = await client.post(
            "/api/v1/qa/ask/stream?mode=agentic",
            json={
                "resume_id": 1,
                "question": "这个人的学历是什么？",
            },
            headers=auth_headers,
        )

    assert resp.status_code == 200
    body = resp.text
    # SSE 流应包含 status、token、done 三种事件
    assert "type" in body
    assert "分析完成" in body or "token" in body
    assert mock_answer in body
    assert '"done"' in body


@pytest.mark.asyncio
async def test_stream_default_mode_does_not_call_agentic(
    client: AsyncClient, auth_headers: dict
):
    """默认 mode（不传或 stream）不应调用 _run_agentic_rag。"""
    with patch(
        "api.qa.resume_service.get_resume",
        new_callable=AsyncMock,
    ), patch(
        "api.qa._run_agentic_rag",
        new_callable=AsyncMock,
    ) as mock_agentic, patch(
        "api.qa._ask_question_stream",
    ) as mock_stream:
        # 让流式管道产生一个 done 事件后结束
        async def fake_stream(*args, **kwargs):
            yield {"type": "done", "answer": "普通流式答案", "sources": []}

        mock_stream.return_value = fake_stream()
        with patch(
            "api.qa.qa_service.save_qa",
            new_callable=AsyncMock,
            return_value=type("R", (), {"id": 1}),
        ):
            await client.post(
                "/api/v1/qa/ask/stream",
                json={
                    "resume_id": 1,
                    "question": "这个人的学历是什么？",
                },
                headers=auth_headers,
            )

    mock_agentic.assert_not_called()
