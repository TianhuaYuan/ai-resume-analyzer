"""Provider-neutral contracts for the AI application layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AIRequest:
    scenario: str = "qa_simple"
    messages: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    user_id: int | None = None
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = 0.1
    max_tokens: int | None = None
    thinking_enabled: bool | None = None
    thinking_effort: str | None = None
    stream: bool = False


@dataclass(frozen=True)
class UsageRecord:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str | None = None
    scenario: str | None = None
    user_id: int | None = None

    @classmethod
    def from_usage(
        cls,
        usage: dict[str, Any] | None,
        *,
        model: str | None = None,
        scenario: str | None = None,
        user_id: int | None = None,
    ) -> "UsageRecord":
        usage = usage or {}
        prompt = max(0, int(usage.get("prompt_tokens", 0) or 0))
        completion = max(0, int(usage.get("completion_tokens", 0) or 0))
        total = max(0, int(usage.get("total_tokens", prompt + completion) or 0))
        return cls(prompt, completion, total, model, scenario, user_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "scenario": self.scenario,
            "user_id": self.user_id,
        }


@dataclass(frozen=True)
class AIResponse:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    reasoning_content: str | None = None
    usage: UsageRecord = field(default_factory=UsageRecord)


@dataclass(frozen=True)
class AIStreamEvent:
    event_type: str
    sequence: int
    turn_id: str
    content: str | None = None
    tool_call_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    protocol_version: str = "1"

    def as_dict(self) -> dict[str, Any]:
        result = {
            "type": self.event_type,
            "event_type": self.event_type,
            "protocol_version": self.protocol_version,
            "sequence": self.sequence,
            "turn_id": self.turn_id,
            **self.payload,
        }
        if self.content is not None:
            result["content"] = self.content
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        return result
