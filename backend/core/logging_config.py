"""结构化 JSON 日志：PII 脱敏 + 采样 + trace_id/span_id。"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

from core.request_id import get_request_id

_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"([a-zA-Z0-9._%+-]{1,2})[a-zA-Z0-9._%+-]*@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"), r"\1***@\2"),
    (re.compile(r"(1[3-9]\d)\d{4}(\d{4})"), r"\1****\2"),
    (re.compile(r"(\d{6})\d{8}(\d{3}[\dXx])"), r"\1********\2"),
    (re.compile(r"(api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*[\"']?([a-zA-Z0-9._\-]{4})[a-zA-Z0-9._\-]+", re.IGNORECASE), r"\1=\2****"),
    (re.compile(r"Bearer\s+([a-zA-Z0-9._\-]{4})[a-zA-Z0-9._\-]+", re.IGNORECASE), r"Bearer \1****"),
]

_PII_FIELD_NAMES = frozenset({
    "email", "phone", "mobile", "id_card", "identity",
    "password", "passwd", "secret", "api_key", "token",
    "authorization", "access_token", "refresh_token",
})


def _filter_pii(text: str) -> str:
    result = text
    for pattern, replacement in _PII_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _filter_pii_dict(data: dict) -> dict:
    filtered = {}
    for key, value in data.items():
        if isinstance(value, str):
            if key.lower() in _PII_FIELD_NAMES:
                filtered[key] = value[:4] + "****" if len(value) > 4 else "****"
            else:
                filtered[key] = _filter_pii(value)
        else:
            filtered[key] = value
    return filtered


class LogSampler:
    def __init__(self, rate: float = 1.0):
        self.rate = max(0.0, min(1.0, rate))

    def should_log(self, request_id: str | None) -> bool:
        if self.rate >= 1.0:
            return True
        if not request_id or self.rate <= 0.0:
            return False
        return (hash(request_id) % 10000) / 10000.0 < self.rate


_sampler: LogSampler | None = None


def _get_sampler() -> LogSampler:
    global _sampler
    if _sampler is None:
        rate = float(os.environ.get("LOG_SAMPLE_RATE", "1.0"))
        _sampler = LogSampler(rate)
    return _sampler


def _json_default(obj):
    """处理 json.dumps 遇到不可序列化类型时降级为 str。"""
    try:
        return str(obj)
    except Exception:
        return f"<{obj.__class__.__name__}: unprintable>"


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = get_request_id()

        sampler = _get_sampler()
        if not sampler.should_log(request_id):
            return ""

        trace_id = getattr(record, "trace_id", None) or request_id or ""
        span_id = format(abs(hash(record.name)) & 0xFFFFFFFF, "08x") if record.name else ""

        log_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": _filter_pii(record.getMessage()),
            "request_id": request_id or "",
            "trace_id": trace_id,
            "span_id": span_id,
        }

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        _builtin_keys = {
            "name", "msg", "args", "created", "relativeCreated", "exc_info",
            "exc_text", "stack_info", "lineno", "funcName", "pathname", "filename",
            "module", "levelname", "levelno", "msecs", "thread", "threadName",
            "process", "processName", "message", "taskName",
        }
        extra_data = {}
        for key, value in record.__dict__.items():
            if key not in _builtin_keys and not key.startswith("_"):
                extra_data[key] = value

        if extra_data:
            log_entry.update(_filter_pii_dict(extra_data))

        result = json.dumps(log_entry, ensure_ascii=False, default=_json_default)
        return result


class SamplingStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if not msg:
            return
        stream = self.stream
        stream.write(msg + self.terminator)
        self.flush()


def setup_logging(level: str = "INFO") -> None:
    sample_rate = float(os.environ.get("LOG_SAMPLE_RATE", "1.0"))
    global _sampler
    _sampler = LogSampler(sample_rate)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    root.handlers.clear()

    handler = SamplingStreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
