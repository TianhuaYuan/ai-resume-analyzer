"""P2-10: 上传 → 处理 → 问答 E2E 集成测试。

走完整 API 链路（不 mock 服务层），只 mock 外部依赖：
- parse_resume（文件解析，避免依赖真实 PDF/DOCX 解析）
- 懒索引（ensure_indexed，避免依赖 ChromaDB）
- _run_agentic_rag（LLM 生成，避免依赖外部 API）

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


async def _wait_for_status(client, resume_id, headers, expected):
    """Poll asynchronous parsing instead of racing the task scheduler."""
    response = None
    for _ in range(100):
        response = await client.get(f"/api/v1/resumes/{resume_id}", headers=headers)
        if response.json().get("status") == expected:
            return response
        await asyncio.sleep(0.02)
    return response


@pytest.mark.asyncio
async def test_upload_pdf_then_ask(
    client: AsyncClient, auth_headers: dict, tmp_path
):
    """E2E: 上传 PDF → 后台处理 → 提问 → 验证答案和历史。"""
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
             "api.qa._run_agentic_rag",
             new_callable=AsyncMock,
             return_value=(fake_answer, fake_sources, []),
         ):
        # 1. 上传简历
        resp = await client.post(
            "/api/v1/resumes",
            files={"file": ("resume.pdf", _make_resume_bytes(), "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 202
        resume_id = resp.json()["id"]
        assert resp.json()["status"] == "processing"

        # 2. 验证后台处理完成（BackgroundTasks 在 ASGITransport 中应已执行）
        resp = await _wait_for_status(client, resume_id, auth_headers, "ready")
        assert resp.status_code == 200
        resume_data = resp.json()
        assert resume_data["status"] == "ready", \
            f"后台任务应将状态改为 ready，实际: {resume_data['status']}"
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
async def test_upload_docx_then_ask(
    client: AsyncClient, auth_headers: dict, tmp_path
):
    """E2E: 上传 DOCX → 后台处理 → 提问。"""
    fake_parsed_text = "李四\nJava 工程师\n5年经验"
    fake_answer = "李四是 Java 工程师，有 5 年经验"
    fake_sources = [{"text": "Java 工程师", "chunk_index": 0, "section": "exp"}]

    with patch("services.resume_service.UPLOAD_DIR", tmp_path), \
         patch(
             "services.resume_service.parse_resume",
             return_value=fake_parsed_text,
         ), \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest), \
         patch(
             "api.qa._run_agentic_rag",
             new_callable=AsyncMock,
             return_value=(fake_answer, fake_sources, []),
         ):
        resp = await client.post(
            "/api/v1/resumes",
            files={
                "file": (
                    "resume.docx",
                    _make_resume_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            headers=auth_headers,
        )
        assert resp.status_code == 202
        resume_id = resp.json()["id"]

        # 等处理完
        resp = await _wait_for_status(client, resume_id, auth_headers, "ready")
        assert resp.json()["status"] == "ready"

        # 提问
        resp = await client.post(
            "/api/v1/qa/ask",
            json={"resume_id": resume_id, "question": "职业？"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["answer"] == fake_answer


@pytest.mark.asyncio
async def test_upload_failed_then_delete(
    client: AsyncClient, auth_headers: dict, tmp_path
):
    """E2E: 上传失败（解析失败）→ 删除简历 → 验证清理。"""
    from pathlib import Path
    from sqlalchemy import select
    from models.resume import Resume

    with patch("services.resume_service.UPLOAD_DIR", tmp_path), \
         patch(
             "services.resume_service.parse_resume",
             side_effect=ValueError("解析失败"),
         ), \
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest), \
         patch(
             "services.resume_service.clear_resume_vectors",
             new_callable=AsyncMock,
         ), \
         patch(
             "services.resume_service.embedding_cache.clear_resume",
             new_callable=AsyncMock,
             return_value=0,
         ):
        # 上传 → 解析失败 → status=failed
        resp = await client.post(
            "/api/v1/resumes",
            files={"file": ("bad.pdf", b"%PDF-1.4\n", "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 202
        resume_id = resp.json()["id"]

        # 确认状态是 failed
        resp = await _wait_for_status(client, resume_id, auth_headers, "failed")
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

        # 从 DB 查 file_path
        async with AsyncSessionTest() as session:
            result = await session.execute(select(Resume).where(Resume.id == resume_id))
            resume = result.scalar_one()
            file_path = resume.file_path

        # 确认文件存在（上传了但解析失败，文件仍在）
        assert Path(file_path).exists()

        # 删除
        resp = await client.delete(f"/api/v1/resumes/{resume_id}", headers=auth_headers)
        assert resp.status_code == 204

        # 验证文件被清理
        assert not Path(file_path).exists()


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
         patch("services.resume_service.AsyncSessionLocal", AsyncSessionTest):
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
