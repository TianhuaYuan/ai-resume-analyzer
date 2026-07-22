"""错误分类模块 — 提供 7 类错误分类供 with_retry 决策。

7 类：
- RATE_LIMIT 限流：429 → 翻倍退避 + 多重试
- TIMEOUT 超时：asyncio.TimeoutError → 少重试
- NON_RETRYABLE 编程错误：TypeError/ValueError → 直接抛
- AUTH 认证失败：401 → 直接抛
- NOT_FOUND 不存在：404 → 直接抛
- NETWORK 网络错误：httpx.ConnectError → 正常重试
- UNKNOWN 未知：其他 → 正常重试

设计参考 AWS 实践：
- 客户端错误（4xx）一般不重试（除 429 限流）
- 服务端错误（5xx）和网络错误重试
- 编程错误（TypeError 等）重试也无法修复
"""

from __future__ import annotations

import asyncio
from enum import Enum


class ErrorCategory(str, Enum):
    """错误分类枚举。

    继承 str + Enum 方便日志输出和 JSON 序列化。
    """

    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NON_RETRYABLE = "non_retryable"
    AUTH = "auth"
    NOT_FOUND = "not_found"
    NETWORK = "network"
    UNKNOWN = "unknown"


# 不可重试的编程错误类型（重试也无法修复）
_NON_RETRYABLE_TYPES = (
    TypeError,
    ValueError,
    AttributeError,
    KeyError,
    IndexError,
    AssertionError,
    NotImplementedError,
)


def _try_import_class(module_path: str, class_name: str):
    """延迟导入，避免在 import 阶段强依赖 openai/httpx。"""
    import importlib

    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name, None)
    except ImportError:
        return None


def classify_error(err: Exception) -> ErrorCategory:
    """根据异常类型返回分类。

    分类优先级（从高到低）：
    1. NON_RETRYABLE — 编程错误（TypeError/ValueError 等）
    2. TIMEOUT — asyncio.TimeoutError / 内置 TimeoutError / openai.APITimeoutError
    3. RATE_LIMIT — openai.RateLimitError
    4. AUTH — openai.AuthenticationError / httpx.HTTPStatusError(401)
    5. NOT_FOUND — openai.NotFoundError / httpx.HTTPStatusError(404)
    6. NETWORK — httpx.ConnectError/ReadError/WriteError/PoolTimeout / openai.APIConnectionError
    7. UNKNOWN — 兜底
    """
    # 1. 编程错误
    if isinstance(err, _NON_RETRYABLE_TYPES):
        return ErrorCategory.NON_RETRYABLE

    # 2. 超时（asyncio.TimeoutError 是 Python 3.11+ 内置 TimeoutError 的别名）
    if isinstance(err, (asyncio.TimeoutError, TimeoutError)):
        return ErrorCategory.TIMEOUT
    openai_api_timeout = _try_import_class("openai", "APITimeoutError")
    if openai_api_timeout and isinstance(err, openai_api_timeout):
        return ErrorCategory.TIMEOUT

    # 3. 限流
    openai_rate_limit = _try_import_class("openai", "RateLimitError")
    if openai_rate_limit and isinstance(err, openai_rate_limit):
        return ErrorCategory.RATE_LIMIT

    # 4. 认证失败
    openai_auth_error = _try_import_class("openai", "AuthenticationError")
    if openai_auth_error and isinstance(err, openai_auth_error):
        return ErrorCategory.AUTH
    httpx_err = _try_import_class("httpx", "HTTPStatusError")
    if httpx_err and isinstance(err, httpx_err):
        response = getattr(err, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            if status_code == 401:
                return ErrorCategory.AUTH
            if status_code == 404:
                return ErrorCategory.NOT_FOUND

    # 5. NotFound
    openai_not_found = _try_import_class("openai", "NotFoundError")
    if openai_not_found and isinstance(err, openai_not_found):
        return ErrorCategory.NOT_FOUND

    # 6. 网络错误
    import httpx as _httpx_mod  # httpx 是项目核心依赖，直接导入
    if isinstance(
        err,
        (
            _httpx_mod.ConnectError,
            _httpx_mod.ReadError,
            _httpx_mod.WriteError,
            _httpx_mod.PoolTimeout,
            _httpx_mod.RemoteProtocolError,
        ),
    ):
        return ErrorCategory.NETWORK
    openai_api_conn = _try_import_class("openai", "APIConnectionError")
    if openai_api_conn and isinstance(err, openai_api_conn):
        return ErrorCategory.NETWORK

    # 7. 兜底
    return ErrorCategory.UNKNOWN
