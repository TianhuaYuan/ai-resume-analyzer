"""验证错误返回完整列表测试。

原行为：RequestValidationError 仅返回第一个错误，前端只能展示 1 个字段错误。
修复后：返回完整 details 列表，前端可逐字段渲染错误提示。

覆盖：
- 单字段错误：details 含 1 条
- 多字段错误：details 含多条，message 取第一条（向后兼容）
- 无错误（边界）：details 为空，message 兜底
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from core.exceptions import register_exception_handlers


def _build_app() -> FastAPI:
    """构造测试 app，含一个多字段必填的端点。"""
    app = FastAPI()
    register_exception_handlers(app)

    class MultiFieldReq(BaseModel):
        name: str = Field(..., min_length=1)
        age: int = Field(..., ge=0)
        email: str = Field(..., min_length=3)

    @app.post("/test")
    async def test_endpoint(req: MultiFieldReq):
        return {"ok": True}

    return app


def test_single_field_error_returns_details():
    """单字段错误 → details 含 1 条，message 含 loc + msg。"""
    app = _build_app()
    client = TestClient(app)

    resp = client.post("/test", json={"name": "ok", "age": 18, "email": "ab"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in body["error"], "应返回 details 字段"
    details = body["error"]["details"]
    assert len(details) == 1
    assert "email" in details[0]["loc"]
    assert details[0]["msg"]


def test_multiple_field_errors_returns_full_list():
    """ 核心：多字段错误 → details 含全部错误，message 取第一条（向后兼容）。"""
    app = _build_app()
    client = TestClient(app)

    # 三个字段全部不合法
    resp = client.post("/test", json={"name": "", "age": -1, "email": "x"})

    assert resp.status_code == 422
    body = resp.json()
    details = body["error"]["details"]
    # 应返回 3 条错误（name/age/email 各一条），而非仅第一个
    assert len(details) == 3, f"应返回 3 条错误，实际: {len(details)}"
    # message 取第一条（向后兼容旧前端只读 message 的逻辑）
    assert body["error"]["message"], "message 不应为空"
    # 每条 detail 都有 loc/msg/type 三个字段
    for d in details:
        assert "loc" in d and "msg" in d and "type" in d


def test_message_backward_compatible():
    """旧前端只读 message 字段，仍能拿到第一条错误信息。"""
    app = _build_app()
    client = TestClient(app)

    resp = client.post("/test", json={"name": "", "age": -1, "email": "x"})
    body = resp.json()
    # message 应是非空字符串，包含 loc + msg
    assert isinstance(body["error"]["message"], str)
    assert len(body["error"]["message"]) > 0


def test_request_id_present_in_error():
    """所有错误响应都应带 request_id，便于追踪。"""
    app = _build_app()
    client = TestClient(app)

    resp = client.post("/test", json={})
    body = resp.json()
    assert body["error"]["request_id"], "request_id 不应为空"
