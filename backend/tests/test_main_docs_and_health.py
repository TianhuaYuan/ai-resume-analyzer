"""Task 1.4: 生产环境 Swagger 关闭 + MCP 健康检查测试。

子任务：
1. ENVIRONMENT=production 时 docs_url/redoc_url/openapi_url 为 None
2. ENVIRONMENT=development 时正常暴露 /docs /redoc /openapi.json
3. /health 响应包含 mcp 字段
4. app.state.mcp_healthy 反映到 /health 的 mcp 字段
"""


from core.config import settings


# ── 子任务 1+2: docs_url 按 ENVIRONMENT 切换 ──

def test_docs_enabled_in_development():
    """development/staging 环境 Swagger/OpenAPI 文档正常暴露。"""
    # 测试环境默认 ENVIRONMENT=development 或 test
    # 这里直接调用 _docs_enabled 函数，避免 reload main 带来的副作用
    from main import _docs_enabled

    # 默认测试环境
    original = settings.ENVIRONMENT
    try:
        settings.ENVIRONMENT = "development"
        assert _docs_enabled() is True

        settings.ENVIRONMENT = "staging"
        assert _docs_enabled() is True
    finally:
        settings.ENVIRONMENT = original


def test_docs_disabled_in_production():
    """production 环境 docs_url/redoc_url/openapi_url 必须为 None。"""
    from main import _docs_enabled

    original = settings.ENVIRONMENT
    try:
        settings.ENVIRONMENT = "production"
        assert _docs_enabled() is False
    finally:
        settings.ENVIRONMENT = original


def test_app_docs_url_reflects_environment():
    """app.docs_url 在当前测试环境（非 production）下应为 /docs。"""
    from main import app

    # 测试环境 ENVIRONMENT 不是 production，docs_url 应该有值
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"


# ── 子任务 3+4: /health 端点 MCP 探针 ──

async def test_health_includes_mcp_field(client):
    """/health 响应必须包含 mcp 字段，值为 healthy / unhealthy。"""
    resp = await client.get("/")
    # 测试环境 chromadb 可能不可达导致 503，但 mcp 字段必须存在
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "mcp" in data
    assert data["mcp"] in ("healthy", "unhealthy")


async def test_health_mcp_unhealthy_when_state_false(client):
    """app.state.mcp_healthy=False 时 /health 返回 mcp=unhealthy。"""
    from main import app

    original = getattr(app.state, "mcp_healthy", None)
    app.state.mcp_healthy = False
    try:
        resp = await client.get("/")
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert data["mcp"] == "unhealthy"
    finally:
        if original is not None:
            app.state.mcp_healthy = original


async def test_health_mcp_healthy_when_state_true(client):
    """app.state.mcp_healthy=True 时 /health 返回 mcp=healthy。"""
    from main import app

    original = getattr(app.state, "mcp_healthy", None)
    app.state.mcp_healthy = True
    try:
        resp = await client.get("/")
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert data["mcp"] == "healthy"
    finally:
        if original is not None:
            app.state.mcp_healthy = original


async def test_health_mcp_field_absent_does_not_crash(client):
    """app.state 没有 mcp_healthy 属性时 /health 不应 500，按 unhealthy 处理。"""
    from main import app

    # 删除 mcp_healthy 属性，模拟 lifespan 未设置（向后兼容场景）
    if hasattr(app.state, "mcp_healthy"):
        original = app.state.mcp_healthy
        del app.state.mcp_healthy
    else:
        original = None

    try:
        resp = await client.get("/")
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert data["mcp"] == "unhealthy"
    finally:
        if original is not None:
            app.state.mcp_healthy = original
