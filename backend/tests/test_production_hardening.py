"""阶段3 生产加固验收测试：安全头 / CORS 收紧 / metrics 认证 / 幂等上传 / 配置校验。

严格按计划 RED→GREEN 编写，仅跑本文件，不影响 MySQL 环境测试。
"""

import pytest
from httpx import AsyncClient

from core.config import settings


# ── 3.1 / 3.3 安全响应头（HSTS / Permissions-Policy + 基础防护头）──
# P2-5: CSP 已迁移到 nginx，后端不再下发 Content-Security-Policy 头
async def test_security_headers_present(client: AsyncClient):
    resp = await client.get("/")  # / 是 health 路由，中间件对全部响应生效
    h = resp.headers
    assert h.get("Strict-Transport-Security", "").startswith("max-age=31536000")
    assert "camera=()" in h.get("Permissions-Policy", "")
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert h.get("Referrer-Policy") == "strict-origin-when-cross-origin"


async def test_csp_header_migrated_to_nginx(client: AsyncClient):
    """P2-5: 后端不再下发 CSP 头，由 nginx 统一管理。"""
    resp = await client.get("/")
    assert "Content-Security-Policy" not in resp.headers, (
        "CSP 应迁移到 nginx，后端不应再下发 Content-Security-Policy 头"
    )


# ── 3.2 CORS 收紧：preflight 不允许通配 ──
async def test_cors_preflight_not_wildcard(client: AsyncClient):
    origin = "http://localhost:5173"  # settings.CORS_ORIGINS 内
    resp = await client.options(
        "/api/v1/resumes",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    allow_headers = resp.headers.get("access-control-allow-headers", "")
    assert "*" not in allow_methods, "allow_methods 不应为通配 *"
    assert "GET" in allow_methods and "POST" in allow_methods and "DELETE" in allow_methods
    assert "*" not in allow_headers, "allow_headers 不应为通配 *"
    assert "Authorization" in allow_headers and "Content-Type" in allow_headers


# ── 3.4 SEC-012：/metrics 需认证 ──
async def test_metrics_requires_auth_without_token(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "secret-metrics-token")
    resp = await client.get("/metrics")
    assert resp.status_code == 403


async def test_metrics_ok_with_valid_token(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "secret-metrics-token")
    resp = await client.get("/metrics", headers={"Authorization": "Bearer secret-metrics-token"})
    # 认证通过即不应再是 403（指标生成本身依赖运行时注册表，不在此断言）
    assert resp.status_code != 403


async def test_metrics_open_when_token_unset(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")
    resp = await client.get("/metrics")
    assert resp.status_code != 403


# ── 3.6 N6：启动配置校验 ──
def test_validate_required_settings_raises_on_missing(monkeypatch):
    from core.config import validate_required_settings

    monkeypatch.setattr(settings, "DATABASE_URL", "")
    with pytest.raises(RuntimeError):
        validate_required_settings()


# ── 3.5 幂等上传：同 Idempotency-Key 不重复创建 ──
async def test_idempotent_upload_returns_existing(
    client: AsyncClient, auth_headers: dict, monkeypatch
):
    import io

    from services import resume_service

    # 隔离外部依赖：文件落盘 + 后台解析（ChromaDB/LLM）不真正执行
    import os

    async def _fake_save(f):
        return (os.path.join("/tmp", f.filename), f.filename)

    monkeypatch.setattr(resume_service, "save_upload_file", _fake_save)
    monkeypatch.setattr(
        resume_service,
        "process_resume_background",
        lambda *a, **k: None,
    )

    files = {"file": ("resume.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    headers = {**auth_headers, "Idempotency-Key": "key-abc-123"}

    r1 = await client.post("/api/v1/resumes", files=files, headers=headers)
    assert r1.status_code == 202
    first_id = r1.json()["id"]

    # 第二次同 key → 应直接返回已有记录（200），不新建
    r2 = await client.post("/api/v1/resumes", files=files, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["id"] == first_id
