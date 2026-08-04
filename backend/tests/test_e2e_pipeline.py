"""P2-10: 上传 → 处理 → 问答 E2E 集成测试。

走完整 API 链路（不 mock 服务层），只 mock 外部依赖：
- parse_resume（文件解析，避免依赖真实 PDF/DOCX 解析）
- 懒索引（ensure_indexed，避免依赖 ChromaDB）
- _run_agentic_rag（LLM 生成，避免依赖外部 API）

A1 改造：解析任务由 BackgroundTasks 改为异步调度（RabbitMQ / create_task），
后台处理不再保证同步完成，测试通过 _wait_ready 轮询等待 ready。

验证：
1. 上传 → 202 + status=processing
2. 后台处理 → status=ready + parsed_text + chunk_count
3. 问答 → 200 + answer + sources
4. 问答历史 → 保存到 DB
5. 幂等上传 → 同 key 返回同一 resume
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import AsyncSessionTest


def _make_resume_bytes() -> bytes:
    """构造一份合法的 txt 简历内容。"""
    return "张三\nPython 工程师\n3年经验\n本科毕业\n熟练 FastAPI 和 LangGraph".encode("utf-8")


async def _wait_ready(
    client: AsyncClient, auth_headers: dict, resume_id: int, max_tries: int = 100
) -> dict:
    """轮询简历状态直到 ready（A1 后解析任务异步执行，不能假设同步完成）。

    Returns:
        ready 时的简历响应数据

    Raises:
        AssertionError: 超过 max_tries 次仍未 ready
    """
    for _ in range(max_tries):
        resp = await client.get(f"/api/v1/resumes/{resume_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] == "ready":
            return data
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"简历 {resume_id} 在 {max_tries} 次轮询内未变为 ready，最终状态: {data['status']}"
    )


@pytest.mark.asyncio
async def test_upload_process_ask_full_pipeline(
    client: AsyncClient, auth_headers: dict, tmp_path
):
    """E2E: 上传 → 后台处理 → 提问 → 验证答案和历史。"""
    fake_parsed_text = "张三\nPython 工程师\n3年经验\n本科毕业"
    fake_answer = "张三是 Python 工程师，有 3 年经验"
    fake_sources = [{"text": "Python 工程师", "chunk_index": 0, "section": "exp"}]

    with patch("services.resume_service.UPLOAD_DIR", tmp_path), \
         patch(
             "services.resume_service.parse_resume",
             return_value=fake_parsed_text,
         ), \
         patch(
             "services.resume_service.AsyncSessionLocal",
             AsyncSessionTest,
         ), \
         patch(
             "services.resume_analyze_producer.publish_analyze_task",
             new_callable=AsyncMock,
         ), \
         patch(
             "services.react_agent.memory.build_l3_profile_background",
             new_callable=AsyncMock,
         ), \
         patch(
             "api.qa._run_agentic_rag",
             new_callable=AsyncMock,
             return_value=(fake_answer, fake_sources, []),
         ):
        # 1. 上传简历
        resp = await client.post(
            "/api/v1/resumes",
            files={"file": ("resume.txt", _make_resume_bytes(), "text/plain")},
            headers=auth_headers,
        )
        assert resp.status_code == 202
        resume_id = resp.json()["id"]
        assert resp.json()["status"] == "processing"

        # 2. 验证后台处理完成（A1: 解析任务异步调度，轮询等待 ready）
        resume_data = await _wait_ready(client, auth_headers, resume_id)
        assert resume_data["status"] == "ready"
        assert resume_data["parsed_text"] == fake_parsed_text
        assert resume_data["chunk_count"] == 0  # 懒索引：上传后未建索引

        # 3. 提问
        resp = await client.post(
            "/api/v1/qa/ask",
            json={"resume_id": resume_id, "question": "这个人的职业是什么？"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        qa_data = resp.json()
        assert qa_data["answer"] == fake_answer
        assert qa_data["degraded"] is False

        # 4. 验证问答历史保存
        resp = await client.get(
            f"/api/v1/qa/history/{resume_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        history = resp.json()
        assert history["total"] == 1
        assert history["items"][0]["question"] == "这个人的职业是什么？"
        assert history["items"][0]["answer"] == fake_answer


@pytest.mark.asyncio
async def test_upload_idempotent_key_returns_same_resume(
    client: AsyncClient, auth_headers: dict, tmp_path
):
    """E2E: 同一 Idempotency-Key 上传两次应返回同一 resume（200 而非 202）。"""
    fake_parsed_text = "李四\nJava 工程师\n5年经验"
    headers_with_key = {**auth_headers, "Idempotency-Key": "e2e-idem-001"}

    with patch("services.resume_service.UPLOAD_DIR", tmp_path), \
         patch(
             "services.resume_service.parse_resume",
             return_value=fake_parsed_text,
         ), \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest), \
         patch(
             "services.resume_analyze_producer.publish_analyze_task",
             new_callable=AsyncMock,
         ), \
         patch(
             "services.react_agent.memory.build_l3_profile_background",
             new_callable=AsyncMock,
         ):
        # 第一次上传 → 202
        resp1 = await client.post(
            "/api/v1/resumes",
            files={"file": ("resume1.txt", b"content1", "text/plain")},
            headers=headers_with_key,
        )
        assert resp1.status_code == 202
        first_id = resp1.json()["id"]

        # 第二次上传（同 key）→ 200，返回同一 resume
        resp2 = await client.post(
            "/api/v1/resumes",
            files={"file": ("resume2.txt", b"content2", "text/plain")},
            headers=headers_with_key,
        )
        assert resp2.status_code == 200
        assert resp2.json()["id"] == first_id, "幂等短路应返回同一 resume_id"


@pytest.mark.asyncio
async def test_upload_then_delete_cleans_file(
    client: AsyncClient, auth_headers: dict, tmp_path
):
    """E2E: 上传文件 → 删除简历 → 验证文件被清理。"""
    from pathlib import Path
    from sqlalchemy import select
    from models.resume import Resume

    fake_parsed_text = "王五\n前端工程师\n2年经验"

    with patch("services.resume_service.UPLOAD_DIR", tmp_path), \
         patch(
             "services.resume_service.parse_resume",
             return_value=fake_parsed_text,
         ), \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest), \
         patch(
             "services.resume_analyze_producer.publish_analyze_task",
             new_callable=AsyncMock,
         ), \
         patch(
             "services.react_agent.memory.build_l3_profile_background",
             new_callable=AsyncMock,
         ), \
         patch(
             "services.resume_service.clear_resume_vectors",
             new_callable=AsyncMock,
         ), \
         patch(
             "services.resume_service.embedding_cache.clear_resume",
             new_callable=AsyncMock,
             return_value=0,
         ):
        # 上传
        resp = await client.post(
            "/api/v1/resumes",
            files={"file": ("resume.txt", _make_resume_bytes(), "text/plain")},
            headers=auth_headers,
        )
        assert resp.status_code == 202
        resume_id = resp.json()["id"]

        # 从 DB 直接查 file_path（API 响应不暴露 file_path）
        async with AsyncSessionTest() as session:
            result = await session.execute(select(Resume).where(Resume.id == resume_id))
            resume = result.scalar_one()
            file_path = resume.file_path

        # 确认文件存在
        assert Path(file_path).exists(), "上传后文件应存在"

        # 删除简历
        resp = await client.delete(f"/api/v1/resumes/{resume_id}", headers=auth_headers)
        assert resp.status_code == 204

        # 验证文件已被删除
        assert not Path(file_path).exists(), "删除简历后文件应被清理"


@pytest.mark.asyncio
async def test_ask_on_nonexistent_resume_returns_404(
    client: AsyncClient, auth_headers: dict
):
    """E2E: 对不存在的 resume 提问应返回 404。"""
    resp = await client.post(
        "/api/v1/qa/ask",
        json={"resume_id": 99999, "question": "这个人的职业是什么？"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_process_ask_degraded_mode(
    client: AsyncClient, auth_headers: dict, tmp_path
):
    """E2E: RAG 检索/重排部分失败时（tool_errors 非空），degraded=True。"""
    fake_parsed_text = "赵六\n全栈工程师\n4年经验"
    fake_answer = "赵六是全栈工程师"
    fake_sources = [{"text": "全栈工程师", "chunk_index": 0, "section": "exp"}]
    fake_tool_errors = [{"step": "rerank", "error": "rerank service timeout"}]

    with patch("services.resume_service.UPLOAD_DIR", tmp_path), \
         patch(
             "services.resume_service.parse_resume",
             return_value=fake_parsed_text,
         ), \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest), \
         patch(
             "services.resume_analyze_producer.publish_analyze_task",
             new_callable=AsyncMock,
         ), \
         patch(
             "services.react_agent.memory.build_l3_profile_background",
             new_callable=AsyncMock,
         ), \
         patch(
             "api.qa._run_agentic_rag",
             new_callable=AsyncMock,
             return_value=(fake_answer, fake_sources, fake_tool_errors),
         ):
        # 上传 + 等后台处理（A1: 异步调度，轮询等待 ready）
        resp = await client.post(
            "/api/v1/resumes",
            files={"file": ("resume.txt", _make_resume_bytes(), "text/plain")},
            headers=auth_headers,
        )
        resume_id = resp.json()["id"]
        await _wait_ready(client, auth_headers, resume_id)

        # 提问
        resp = await client.post(
            "/api/v1/qa/ask",
            json={"resume_id": resume_id, "question": "职业是什么？"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        qa_data = resp.json()
        assert qa_data["answer"] == fake_answer
        assert qa_data["degraded"] is True, "tool_errors 非空时 degraded 应为 True"
