"""统一错误分类与 RAGError 基类。

用途：将散落在各处的异常归类，支撑重试策略（阶段1.2）、
错误透传（阶段4）与监控指标（阶段10）对错误做差异化处理。
"""

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    pass


class ErrorCategory(str, Enum):
    """错误大类，决定重试 / 告警 / 透传行为。"""

    NON_RETRYABLE = "non_retryable"  # 编程错误，立即抛出
    RETRYABLE = "retryable"  # 瞬时错误，可重试
    TIMEOUT = "timeout"  # 超时，可重试
    RATE_LIMIT = "rate_limit"  # 限流，退避后重试
    AUTH = "auth"  # 鉴权失败
    NOT_FOUND = "not_found"  # 资源不存在
    UPSTREAM = "upstream"  # 上游 LLM / 向量库 / rerank 失败


class RAGError(Exception):
    """RAG 流程统一异常，携带分类与建议 HTTP 状态码。"""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.NON_RETRYABLE,
        status_code: int = 500,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.category = category
        self.status_code = status_code

    def __str__(self) -> str:
        return f"[{self.category.value}] {self.message}"


# 异常类型 → 分类 的精确映射
_TYPE_MAP: dict[type, ErrorCategory] = {
    TimeoutError: ErrorCategory.TIMEOUT,
    ConnectionError: ErrorCategory.UPSTREAM,
    ValueError: ErrorCategory.NON_RETRYABLE,
    KeyError: ErrorCategory.NON_RETRYABLE,
    TypeError: ErrorCategory.NON_RETRYABLE,
    FileNotFoundError: ErrorCategory.NOT_FOUND,
}

# 关键字 → 分类 的启发式（无类型匹配时回退）
_KEYWORD_MAP: list[tuple[str, ErrorCategory]] = [
    ("timeout", ErrorCategory.TIMEOUT),
    ("rate limit", ErrorCategory.RATE_LIMIT),
    ("429", ErrorCategory.RATE_LIMIT),
    ("401", ErrorCategory.AUTH),
    ("403", ErrorCategory.AUTH),
    ("not found", ErrorCategory.NOT_FOUND),
    ("404", ErrorCategory.NOT_FOUND),
    ("connection", ErrorCategory.UPSTREAM),
    ("chroma", ErrorCategory.UPSTREAM),
    ("rerank", ErrorCategory.UPSTREAM),
    ("embedding", ErrorCategory.UPSTREAM),
]


def classify_error(exc: Exception) -> ErrorCategory:
    """将任意异常归类为 ErrorCategory：先按类型，再按消息关键字。"""
    category = _TYPE_MAP.get(type(exc))
    if category is not None:
        return category
    text = str(exc).lower()
    for keyword, cat in _KEYWORD_MAP:
        if keyword in text:
            return cat
    return ErrorCategory.RETRYABLE
