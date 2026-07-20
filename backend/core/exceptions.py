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


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": get_request_id(),
            }
        },
    )


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
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc = " -> ".join(str(part) for part in first.get("loc", []))
            msg = f"{loc}: {first.get('msg', '参数校验失败')}"
        else:
            msg = "参数校验失败"
        logger.warning("ValidationError: %s", msg)
        return _error_response(422, "VALIDATION_ERROR", msg)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return _error_response(500, "INTERNAL_ERROR", "服务器内部错误，请稍后重试")
