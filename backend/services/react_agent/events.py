"""流式事件标准化 — 标准事件类型定义与构造器（借鉴 OpenClaw EventStream）。

目标：为 Agent SSE 流定义**唯一事件字典**，消除散落各处的魔法字符串。
每个事件用构造函数生成，保证字段一致、前端解析稳定。

事件族（每族 start/delta/end 三段式）：
- text：最终答案文本（answer_token → text_start/text_delta/text_end）
- thinking：模型推理过程（agent_thought → thinking_start/thinking_delta/thinking_end）
- toolcall：工具调用（tool_call → toolcall_start/toolcall_end；tool_result/tool_error 并行）

控制类事件：
- agent_start / agent_done / usage / quota_exceeded / injection / approval_*

注意：本模块只做**定义与构造**，不改写现有 emit 调用（避免破坏既有前端协议）。
新代码一律用本模块构造事件；存量事件迁移是独立任务。
"""

from __future__ import annotations

from typing import Any

# ── 文本事件族 ──────────────────────────────────────────────
TEXT_START = "text_start"
TEXT_DELTA = "text_delta"
TEXT_END = "text_end"

# ── 推理事件族 ──────────────────────────────────────────────
THINKING_START = "thinking_start"
THINKING_DELTA = "thinking_delta"
THINKING_END = "thinking_end"

# ── 工具调用事件族 ──────────────────────────────────────────
TOOLCALL_START = "toolcall_start"
TOOLCALL_END = "toolcall_end"
TOOL_RESULT = "tool_result"
TOOL_ERROR = "tool_error"

# ── 控制/生命周期事件 ───────────────────────────────────────
AGENT_START = "agent_start"
AGENT_DONE = "agent_done"
AGENT_THOUGHT = "agent_thought"  # 兼容别名（thinking_delta 前身）
ANSWER_TOKEN = "answer_token"  # 兼容别名（text_delta 前身）
USAGE = "usage"
QUOTA_EXCEEDED = "quota_exceeded"
INJECTION = "injection"
ERROR = "error"
APPROVAL_REQUEST = "approval_request"
APPROVAL_DECISION = "approval_decision"


def text_start() -> dict[str, Any]:
    return {"type": TEXT_START}


def text_delta(content: str) -> dict[str, Any]:
    return {"type": TEXT_DELTA, "content": content}


def text_end() -> dict[str, Any]:
    return {"type": TEXT_END}


def thinking_start() -> dict[str, Any]:
    return {"type": THINKING_START}


def thinking_delta(content: str) -> dict[str, Any]:
    return {"type": THINKING_DELTA, "content": content}


def thinking_end() -> dict[str, Any]:
    return {"type": THINKING_END}


def toolcall_start(name: str, arguments: str, id: str) -> dict[str, Any]:
    return {"type": TOOLCALL_START, "name": name, "arguments": arguments, "id": id}


def toolcall_end(name: str, id: str) -> dict[str, Any]:
    return {"type": TOOLCALL_END, "name": name, "id": id}


def tool_result(name: str, result: str, id: str) -> dict[str, Any]:
    return {"type": TOOL_RESULT, "name": name, "result": result, "id": id}


def tool_error(name: str, error: str, id: str) -> dict[str, Any]:
    return {"type": TOOL_ERROR, "name": name, "error": error, "id": id}


def agent_start(*, mode: str = "agent") -> dict[str, Any]:
    return {"type": AGENT_START, "mode": mode}


def agent_done(
    answer: str,
    *,
    qa_id: int | None = None,
    process_trace: list[dict] | None = None,
    usage: dict | None = None,
    degraded: bool = False,
) -> dict[str, Any]:
    ev: dict[str, Any] = {"type": AGENT_DONE, "answer": answer}
    if qa_id is not None:
        ev["qa_id"] = qa_id
    if process_trace is not None:
        ev["process_trace"] = process_trace
    if usage is not None:
        ev["token_usage"] = usage
    if degraded:
        ev["degraded"] = True
    return ev


def usage(usage: dict[str, Any], total: dict[str, Any]) -> dict[str, Any]:
    return {"type": USAGE, "usage": usage, "total": total}


def quota_exceeded(message: str) -> dict[str, Any]:
    return {"type": QUOTA_EXCEEDED, "message": message}


def error(message: str) -> dict[str, Any]:
    return {"type": ERROR, "message": message}
