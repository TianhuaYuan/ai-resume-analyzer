"""T7: 安全头 CSP + Origin/Referer 校验 + ASGI 请求体限制。

测试范围：
- CSP 头在 API 响应中存在且策略正确
- Origin/Referer 校验对敏感路由生效，开发环境跳过
- ASGI receive 包装限制真实读取量
"""

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from unittest.mock import patch


# ═══════════════════════════════════════════════════════════
# CSP 头测试
# ═══════════════════════════════════════════════════════════


class TestCspHeaders:
    """CSP 安全头补充。"""

    def test_csp_header_present(self, client):
        """任意 API 响应应包含 Content-Security-Policy 头。"""
        resp = client.get("/")
        assert "content-security-policy" in resp.headers

    def test_csp_default_src_none(self, client):
        """CSP 应包含 default-src 'none'（API 不加载外部资源）。"""
        resp = client.get("/")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'none'" in csp

    def test_csp_frame_ancestors_none(self, client):
        """CSP 应包含 frame-ancestors 'none'（禁止被嵌入 iframe）。"""
        resp = client.get("/")
        csp = resp.headers.get("content-security-policy", "")
        assert "frame-ancestors 'none'" in csp


# ═══════════════════════════════════════════════════════════
# Origin/Referer 校验测试
# ═══════════════════════════════════════════════════════════


class TestOriginVerification:
    """Origin/Referer 校验：敏感路由防 CSRF。"""

    def test_valid_origin_allowed(self, client):
        """Origin 在白名单中应允许访问。"""
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "test@test.com", "password": "123456"},
            headers={"Origin": "http://localhost:5173"},
        )
        # 即使登录失败，也不应因 Origin 被拒（应是 401 而非 403）
        assert resp.status_code != 403

    def test_invalid_origin_rejected(self, client):
        """Origin 不在白名单中应返回 403。"""
        with patch("core.security.settings.ENVIRONMENT", "production"):
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "test@test.com", "password": "123456"},
                headers={"Origin": "https://evil.com"},
            )
        assert resp.status_code == 403

    def test_referer_fallback_allowed(self, client):
        """无 Origin 但 Referer 在白名单中应允许。"""
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "test@test.com", "password": "123456"},
            headers={"Referer": "http://localhost:5173/login"},
        )
        assert resp.status_code != 403

    def test_invalid_referer_rejected(self, client):
        """Referer 不在白名单中应返回 403。"""
        with patch("core.security.settings.ENVIRONMENT", "production"):
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "test@test.com", "password": "123456"},
                headers={"Referer": "https://evil.com/phishing"},
            )
        assert resp.status_code == 403

    def test_non_sensitive_route_skips_origin_check(self, client):
        """非敏感路由（如 /health）不应校验 Origin。"""
        with patch("core.security.settings.ENVIRONMENT", "production"):
            resp = client.get("/", headers={"Origin": "https://evil.com"})
        # 健康检查可能因数据库不可用返回 503，只要不是 403 就说明 Origin 校验没生效
        assert resp.status_code != 403


# ═══════════════════════════════════════════════════════════
# ASGI 请求体限制测试
# ═══════════════════════════════════════════════════════════


class TestAsgiBodyLimit:
    """ASGI receive 包装限制真实读取量。"""

    def test_small_body_allowed(self, client):
        """小请求体应正常通过。"""
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "test@test.com", "password": "123"},
        )
        # 不应因请求体大小被拒
        assert resp.status_code != 413

    def test_large_body_rejected(self, client):
        """超大请求体应返回 413（即使 Content-Length 未预检到）。"""
        # 构造一个超过限制的 body（模拟 Content-Length 伪造）
        huge_body = b'{"x": "' + b"a" * (15 * 1024 * 1024) + b'"}'  # 15MB
        resp = client.post(
            "/api/v1/auth/login",
            content=huge_body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def client():
    """返回已配置所有中间件的 TestClient。

    注意：直接使用 main.app 的 TestClient，这样所有 middleware 都生效。
    """
    from main import app
    return TestClient(app)
