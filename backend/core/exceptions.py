"""全局异常处理：AppException 业务异常 + 统一 JSON 错误格式。"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.request_id import get_request_id

logger = logging.getLogger(__name__)


class AppException(Exception):
    def __init__(self, status_code: int, detail: str, error_code: str = "APP_ERROR"):
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        super().__init__(detail)


def _error_response(status_code: int, code: str, message: str, details: list | None = None) -> JSONResponse:
    """统一错误响应构造。

    Args:
        status_code: HTTP 状态码
        code: 业务错误码（如 VALIDATION_ERROR）
        message: 人类可读的主错误消息（向后兼容）
        details: P3-11 完整错误列表，每个元素含 {loc, msg, type}，
                 前端可逐字段渲染错误提示。仅校验类错误填充。
    """
    body: dict = {
        "error": {
            "code": code,
            "message": message,
            "request_id": get_request_id(),
        }
    }
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        logger.warning("AppException: [%s] %s", exc.error_code, exc.detail)
        return _error_response(exc.status_code, exc.error_code, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = f"HTTP_{exc.status_code}"
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _error_response(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # P3-11: 返回完整错误列表而非仅第一个，前端可逐字段展示
        raw_errors = exc.errors()
        details: list[dict] = []
        for err in raw_errors:
            loc = " -> ".join(str(part) for part in err.get("loc", []))
            details.append({
                "loc": loc,
                "msg": err.get("msg", "参数校验失败"),
                "type": err.get("type", ""),
            })
        # message 取第一个错误的消息作为主消息（向后兼容旧前端只读 message 的逻辑）
        if details:
            message = f"{details[0]['loc']}: {details[0]['msg']}"
        else:
            message = "参数校验失败"
        logger.warning("ValidationError: %d 个错误，首个: %s", len(details), message)
        return _error_response(422, "VALIDATION_ERROR", message, details=details)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return _error_response(500, "INTERNAL_ERROR", "服务器内部错误，请稍后重试")
