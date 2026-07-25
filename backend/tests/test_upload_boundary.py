"""P2-8: 文件上传边界测试。

覆盖扩展名/MIME/大小/空文件等边界场景。
"""
import io

import pytest
from httpx import AsyncClient


@pytest.fixture
async def auth_headers(client, registered_user):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": registered_user["password"]},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_upload_invalid_extension_rejected(client: AsyncClient, auth_headers: dict):
    """.exe 扩展名应被拒绝。"""
    file_content = b"MZ\x90\x00" * 10
    files = {"file": ("malicious.exe", io.BytesIO(file_content), "application/octet-stream")}
    r = await client.post("/api/v1/resumes", files=files, headers=auth_headers)
    assert 400 <= r.status_code < 500, f"应被拒绝，实际状态 {r.status_code}: {r.text}"


async def test_upload_png_extension_rejected(client: AsyncClient, auth_headers: dict):
    """.png 扩展名应被拒绝（400）。"""
    file_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    files = {"file": ("screenshot.png", io.BytesIO(file_content), "image/png")}
    r = await client.post("/api/v1/resumes", files=files, headers=auth_headers)
    assert r.status_code == 400


async def test_upload_invalid_mime_rejected(client: AsyncClient, auth_headers: dict):
    """扩展名为 .pdf 但 MIME 为 image/jpeg 应被拒绝。"""
    file_content = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    files = {"file": ("fake.pdf", io.BytesIO(file_content), "image/jpeg")}
    r = await client.post("/api/v1/resumes", files=files, headers=auth_headers)
    assert 400 <= r.status_code < 500, f"应被拒绝，实际状态 {r.status_code}: {r.text}"


async def test_upload_empty_file_accepted(client: AsyncClient, auth_headers: dict):
    """0 字节 PDF 文件（扩展名合法）应被接受并进入处理流程。"""
    files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    r = await client.post("/api/v1/resumes", files=files, headers=auth_headers)
    assert r.status_code in (200, 202)


async def test_upload_valid_pdf(client: AsyncClient, auth_headers: dict):
    """正常 PDF 上传应返回 202。"""
    pdf_header = b"%PDF-1.4\n%EOF\n"
    files = {"file": ("resume.pdf", io.BytesIO(pdf_header), "application/pdf")}
    r = await client.post("/api/v1/resumes", files=files, headers=auth_headers)
    assert r.status_code == 202
    data = r.json()
    assert "id" in data
    assert data["filename"] == "resume.pdf"


async def test_upload_valid_docx(client: AsyncClient, auth_headers: dict):
    """正常 DOCX 上传应返回 202。"""
    docx_content = b"PK\x03\x04" + b"\x00" * 200
    files = {"file": ("resume.docx", io.BytesIO(docx_content), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    r = await client.post("/api/v1/resumes", files=files, headers=auth_headers)
    assert r.status_code == 202
    assert r.json()["filename"] == "resume.docx"


async def test_upload_oversized_file_rejected(client: AsyncClient, auth_headers: dict):
    """超过 MAX_UPLOAD_SIZE_MB 的文件应被拒绝（413）。

    系统有两层防御：
    1. 中间件层（MAX_REQUEST_BODY_MB）：Content-Length 预检，快速 413
    2. 服务层（MAX_UPLOAD_SIZE_MB）：流式写入实时检查，兜底 413
    只要状态码是 413 即通过。
    """
    from core.config import settings
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    oversized_content = b"x" * (max_bytes + 1)
    files = {"file": ("big.pdf", io.BytesIO(oversized_content), "application/pdf")}
    r = await client.post("/api/v1/resumes", files=files, headers=auth_headers)
    assert r.status_code == 413


async def test_upload_requires_auth(client: AsyncClient):
    """未登录上传应返回 401。"""
    files = {"file": ("resume.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
    r = await client.post("/api/v1/resumes", files=files)
    assert r.status_code == 401
