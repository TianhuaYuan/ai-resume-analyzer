"""Transport-neutral tool result contract.

The legacy agent loop still consumes text/tuples.  This module gives the
execution boundary one lossless representation without coupling tools to SSE
or FastAPI; adapters can project it to the legacy protocol during migration.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

ToolStatus = Literal["succeeded", "failed", "rejected", "cancelled"]


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False
    category: str = "tool"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultEnvelope:
    call_id: str
    tool_name: str
    status: ToolStatus
    output: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    error: ToolError | None = None
    usage: dict[str, int] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retryable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("successful tool result cannot contain an error")
        if self.status != "succeeded" and self.error is None:
            raise ValueError("failed/rejected/cancelled tool result requires an error")
        if self.error is not None:
            self.retryable = self.error.retryable

    @property
    def is_error(self) -> bool:
        return self.status != "succeeded"

    def to_model_content(self) -> str:
        """Return bounded, model-safe text while keeping error semantics out of evidence."""
        if self.status == "succeeded":
            return self.output or ""
        assert self.error is not None
        return f"[{self.error.code}] {self.error.message}"

    def to_legacy_tuple(self) -> tuple[str, bool, list[dict[str, Any]], dict[str, int]]:
        return (self.to_model_content(), self.is_error, self.evidence, self.usage)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["error"] = asdict(self.error) if self.error else None
        payload["started_at"] = self.started_at.isoformat()
        payload["finished_at"] = self.finished_at.isoformat()
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def success(*, call_id: str, tool_name: str, output: str, evidence=None, usage=None, started_at=None) -> ToolResultEnvelope:
    return ToolResultEnvelope(
        call_id=call_id,
        tool_name=tool_name,
        status="succeeded",
        output=output,
        evidence=list(evidence or []),
        usage=dict(usage or {}),
        started_at=started_at or datetime.now(timezone.utc),
    )


def failure(*, call_id: str, tool_name: str, code: str, message: str, retryable: bool, category: str = "tool", status: ToolStatus = "failed", started_at=None, evidence=None, usage=None) -> ToolResultEnvelope:
    err = ToolError(code=code, message=message, retryable=retryable, category=category)
    return ToolResultEnvelope(
        call_id=call_id,
        tool_name=tool_name,
        status=status,
        error=err,
        evidence=list(evidence or []),
        usage=dict(usage or {}),
        retryable=retryable,
        started_at=started_at or datetime.now(timezone.utc),
    )


def from_legacy(
    *,
    call_id: str,
    tool_name: str,
    output: str,
    is_error: bool,
    evidence: list[dict[str, Any]] | None = None,
    usage: dict[str, int] | None = None,
    retryable: bool = False,
) -> ToolResultEnvelope:
    """Lift the current tuple contract into the canonical envelope.

    This is intentionally an adapter: legacy tools remain callable while the
    runtime, trace and transports can start consuming one lossless shape.
    """
    if not is_error:
        return success(
            call_id=call_id,
            tool_name=tool_name,
            output=output,
            evidence=evidence,
            usage=usage,
        )
    return failure(
        call_id=call_id,
        tool_name=tool_name,
        code="retryable_tool_error" if retryable else "business_rejected",
        message=output,
        retryable=retryable,
        evidence=evidence,
        usage=usage,
    )
