"""工具结果中间件 — 链式处理工具执行结果。

与 tool_hooks 的分工：
- tool_hooks：**执行前后**拦截（before: 审批/参数重写；after: 覆盖结果/终止循环）
- 本模块：**结果纯变换管线**——对工具返回的字符串结果做链式清洗
  （截断/脱敏/来源标注），处理函数无副作用，可组合、可复用。

预置中间件：
1. TruncationMiddleware：截断超长结果（预算随上下文窗口自适应）
2. SanitizationMiddleware：脱敏敏感信息（手机号/邮箱/身份证/密钥）
3. SourceTagMiddleware：为结果附加来源标注（配合 Provenance 追踪）

用法：
    pipeline = ToolResultPipeline([
        SanitizationMiddleware(),
        TruncationMiddleware(max_chars=6000),
    ])
    clean = await pipeline.process("原始工具结果", tool_name="web_search")
"""

from __future__ import annotations

import re
from typing import Protocol


class ToolResultMiddleware(Protocol):
    """工具结果中间件协议：async 处理函数，链式传递结果。"""

    async def process(self, result: str, *, tool_name: str) -> str: ...


# 敏感信息脱敏规则（保守匹配，宁可误标不泄漏）
_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"1[3-9]\d{9}"), "[手机号]"),  # 中国大陆手机号
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[邮箱]"),
    (re.compile(r"\b\d{17}[\dXx]\b"), "[身份证号]"),
    (re.compile(r"\b(sk|pk|api)_[A-Za-z0-9]{8,}\b"), "[密钥]"),
    (re.compile(r"\b\d{16,19}\b"), "[银行卡号]"),
]


class TruncationMiddleware:
    """截断中间件：超长结果按预算截断（随上下文窗口自适应）。"""

    def __init__(self, max_chars: int | None = None) -> None:
        self.max_chars = max_chars

    async def process(self, result: str, *, tool_name: str) -> str:
        budget = self.max_chars
        if budget is None:
            try:
                from services.react_agent.loop import _tool_result_budget

                budget = _tool_result_budget()
            except Exception:
                budget = 6000
        if len(result) <= budget:
            return result
        return result[: budget - 3] + "..."


class SanitizationMiddleware:
    """脱敏中间件：替换结果中的敏感信息（手机号/邮箱/身份证/密钥/银行卡）。"""

    async def process(self, result: str, *, tool_name: str) -> str:
        for pattern, repl in _SENSITIVE_PATTERNS:
            result = pattern.sub(repl, result)
        return result


class SourceTagMiddleware:
    """来源标注中间件：为结果附加来源标记（配合 Provenance 追踪）。

    仅对非系统工具结果附加（避免污染系统脚手架内容）。
    """

    _TAGGED_TOOLS = frozenset({"search_resume", "search_assets", "web_search"})

    async def process(self, result: str, *, tool_name: str) -> str:
        if tool_name in self._TAGGED_TOOLS and result and not result.startswith("⚠️"):
            return f"[来源:{tool_name}] {result}"
        return result


class ToolResultPipeline:
    """工具结果处理管线：按序执行中间件，结果链式传递。"""

    def __init__(self, middlewares: list[ToolResultMiddleware] | None = None) -> None:
        self.middlewares: list[ToolResultMiddleware] = middlewares or [
            SanitizationMiddleware(),
            TruncationMiddleware(),
        ]

    def add(self, middleware: ToolResultMiddleware) -> "ToolResultPipeline":
        """追加中间件（链式调用，可复用）。"""
        self.middlewares.append(middleware)
        return self

    async def process(self, result: str, *, tool_name: str) -> str:
        """依次执行中间件。单个中间件异常不阻断管线（降级为原结果）。"""
        current = result
        for mw in self.middlewares:
            try:
                current = await mw.process(current, tool_name=tool_name)
            except Exception:
                # 中间件异常不影响主流程（结果保持上一步状态）
                continue
        return current


# 模块级默认管线（复用实例，避免每次重建）
_default_pipeline = ToolResultPipeline()


async def process_tool_result(result: str, *, tool_name: str) -> str:
    """便捷入口：用默认管线处理工具结果。"""
    return await _default_pipeline.process(result, tool_name=tool_name)
