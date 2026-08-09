"""
工具钩子系统 — before/after 执行拦截

借鉴 OpenClaw 的 beforeToolCall/afterToolCall 机制：
- before 钩子：工具执行前拦截（block/rewrite/requireApproval）
- after 钩子：工具执行后处理（override/terminate）
- 全局钩子 + 工具特定钩子
- 异步执行，异常不阻断主流程

使用场景：
1. 审批门：before 钩子检查工具是否需要审批
2. 参数重写：before 钩子重写工具参数
3. 结果过滤：after 钩子过滤敏感信息
4. 终止循环：after 钩子判断是否需要终止
5. 日志记录：after 钩子记录执行结果
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

# ── 钩子动作枚举 ──


class HookAction(str, Enum):
    """钩子动作"""

    ALLOW = "allow"  # 允许执行
    BLOCK = "block"  # 阻止执行
    REWRITE = "rewrite"  # 重写参数
    OVERRIDE = "override"  # 覆盖结果
    TERMINATE = "terminate"  # 终止循环


# ── 上下文数据结构 ──


@dataclass
class ToolCallContext:
    """工具调用上下文 — 传递给 before 钩子，可修改参数或阻止执行"""

    tool_name: str
    args: dict
    tool_call_id: str
    user_id: int
    resume_id: int
    session_key: str | None = None

    # 可修改字段（由钩子设置）
    _blocked: bool = field(default=False, repr=False)
    _block_reason: str = field(default="", repr=False)
    _rewritten_args: dict | None = field(default=None, repr=False)

    def block(self, reason: str) -> None:
        """阻止工具执行"""
        self._blocked = True
        self._block_reason = reason

    def rewrite_args(self, new_args: dict) -> None:
        """重写工具参数"""
        self._rewritten_args = new_args

    @property
    def is_blocked(self) -> bool:
        """是否已被钩子阻止"""
        return self._blocked

    @property
    def block_reason(self) -> str:
        """阻止原因"""
        return self._block_reason

    @property
    def final_args(self) -> dict:
        """最终参数：优先返回重写后的参数"""
        return self._rewritten_args if self._rewritten_args is not None else self.args


@dataclass
class ToolResultContext:
    """工具结果上下文 — 传递给 after 钩子，可覆盖结果或终止循环"""

    tool_name: str
    args: dict
    result: Any
    tool_call_id: str
    duration_ms: float
    success: bool

    # 可修改字段（由钩子设置）
    _overridden_result: Any | None = field(default=None, repr=False)
    _terminate: bool = field(default=False, repr=False)
    _terminate_reason: str = field(default="", repr=False)

    def override_result(self, new_result: Any) -> None:
        """覆盖工具返回结果"""
        self._overridden_result = new_result

    def terminate_loop(self, reason: str) -> None:
        """发出终止 Agent 循环的信号"""
        self._terminate = True
        self._terminate_reason = reason

    @property
    def final_result(self) -> Any:
        """最终结果：优先返回覆盖后的结果"""
        return self._overridden_result if self._overridden_result is not None else self.result

    @property
    def should_terminate(self) -> bool:
        """是否应终止 Agent 循环"""
        return self._terminate

    @property
    def terminate_reason(self) -> str:
        """终止原因"""
        return self._terminate_reason


# ── 钩子函数类型别名 ──

BeforeHookFunc = Callable[[ToolCallContext], Awaitable[None]]
AfterHookFunc = Callable[[ToolResultContext], Awaitable[None]]


# ── 钩子管理器 ──


class ToolHookManager:
    """工具钩子管理器：before/after 钩子注册与执行

    设计要点：
    - 支持全局钩子（所有工具生效）和工具特定钩子
    - 全局钩子先于工具特定钩子执行
    - 钩子异常静默吞掉，不阻断主流程
    - before 钩子链中任意一个 block() 则阻止执行
    - after 钩子链中任意一个 terminate_loop() 则终止 Agent 循环
    """

    def __init__(self) -> None:
        self._before_hooks: dict[str, list[BeforeHookFunc]] = {}
        self._after_hooks: dict[str, list[AfterHookFunc]] = {}
        self._global_before: list[BeforeHookFunc] = []
        self._global_after: list[AfterHookFunc] = []

    # ── 装饰器注册 ──

    def register_before(self, tool_name: str | None = None) -> Callable:
        """注册 before 钩子（装饰器模式）

        Args:
            tool_name: 指定工具名则仅对该工具生效，None 表示全局钩子

        Usage:
            @hook_manager.register_before("search_jobs")
            async def audit_search(context: ToolCallContext):
                ...
        """

        def decorator(func: BeforeHookFunc) -> BeforeHookFunc:
            if tool_name:
                self._before_hooks.setdefault(tool_name, []).append(func)
            else:
                self._global_before.append(func)
            return func

        return decorator

    def register_after(self, tool_name: str | None = None) -> Callable:
        """注册 after 钩子（装饰器模式）

        Args:
            tool_name: 指定工具名则仅对该工具生效，None 表示全局钩子

        Usage:
            @hook_manager.register_after("rewrite_resume")
            async def log_rewrite(context: ToolResultContext):
                ...
        """

        def decorator(func: AfterHookFunc) -> AfterHookFunc:
            if tool_name:
                self._after_hooks.setdefault(tool_name, []).append(func)
            else:
                self._global_after.append(func)
            return func

        return decorator

    # ── 非装饰器注册 ──

    def add_before(self, hook: BeforeHookFunc, tool_name: str | None = None) -> None:
        """添加 before 钩子（非装饰器方式）

        Args:
            hook: 异步钩子函数
            tool_name: 指定工具名，None 表示全局
        """
        if tool_name:
            self._before_hooks.setdefault(tool_name, []).append(hook)
        else:
            self._global_before.append(hook)

    def add_after(self, hook: AfterHookFunc, tool_name: str | None = None) -> None:
        """添加 after 钩子（非装饰器方式）

        Args:
            hook: 异步钩子函数
            tool_name: 指定工具名，None 表示全局
        """
        if tool_name:
            self._after_hooks.setdefault(tool_name, []).append(hook)
        else:
            self._global_after.append(hook)

    # ── 执行 ──

    async def run_before(self, context: ToolCallContext) -> bool:
        """执行 before 钩子链，返回是否允许工具执行

        执行顺序：全局钩子 → 工具特定钩子
        任意钩子调用 context.block() 后，后续钩子仍会执行（可观察阻止原因），
        但最终返回 False 表示不允许执行。

        Args:
            context: 工具调用上下文，钩子可修改其中的参数或阻止执行

        Returns:
            True 表示允许执行，False 表示已被阻止
        """
        logger = logging.getLogger("react_agent.hooks")

        # 全局钩子
        for hook in self._global_before:
            try:
                await hook(context)
            except Exception as e:
                logger.warning(
                    "全局 before 钩子 %s 执行异常: %s", hook.__name__, e, exc_info=True
                )

        # 工具特定钩子
        for hook in self._before_hooks.get(context.tool_name, []):
            try:
                await hook(context)
            except Exception as e:
                logger.warning(
                    "工具 %s 的 before 钩子 %s 执行异常: %s",
                    context.tool_name,
                    hook.__name__,
                    e,
                    exc_info=True,
                )

        if context.is_blocked:
            logger.info(
                "工具 %s 被阻止执行，原因: %s",
                context.tool_name,
                context.block_reason,
            )

        return not context.is_blocked

    async def run_after(self, context: ToolResultContext) -> bool:
        """执行 after 钩子链，返回是否继续 Agent 循环

        执行顺序：全局钩子 → 工具特定钩子
        任意钩子调用 context.terminate_loop() 后，后续钩子仍会执行，
        但最终返回 False 表示应终止循环。

        Args:
            context: 工具结果上下文，钩子可覆盖结果或终止循环

        Returns:
            True 表示继续循环，False 表示应终止
        """
        logger = logging.getLogger("react_agent.hooks")

        # 全局钩子
        for hook in self._global_after:
            try:
                await hook(context)
            except Exception as e:
                logger.warning(
                    "全局 after 钩子 %s 执行异常: %s", hook.__name__, e, exc_info=True
                )

        # 工具特定钩子
        for hook in self._after_hooks.get(context.tool_name, []):
            try:
                await hook(context)
            except Exception as e:
                logger.warning(
                    "工具 %s 的 after 钩子 %s 执行异常: %s",
                    context.tool_name,
                    hook.__name__,
                    e,
                    exc_info=True,
                )

        if context.should_terminate:
            logger.info(
                "Agent 循环被终止，工具: %s，原因: %s",
                context.tool_name,
                context.terminate_reason,
            )

        return not context.should_terminate

    # ── 管理 ──

    def clear(self, tool_name: str | None = None) -> None:
        """清除钩子

        Args:
            tool_name: 指定工具名则仅清除该工具的钩子，None 清除全部
        """
        if tool_name:
            self._before_hooks.pop(tool_name, None)
            self._after_hooks.pop(tool_name, None)
        else:
            self._before_hooks.clear()
            self._after_hooks.clear()
            self._global_before.clear()
            self._global_after.clear()

    def has_hooks(self, tool_name: str | None = None) -> bool:
        """检查是否有注册的钩子

        Args:
            tool_name: 指定工具名则检查该工具是否有钩子，None 检查全局

        Returns:
            是否存在至少一个钩子
        """
        if tool_name:
            return bool(
                self._before_hooks.get(tool_name) or self._after_hooks.get(tool_name)
            )
        return bool(
            self._global_before
            or self._global_after
            or self._before_hooks
            or self._after_hooks
        )

    @property
    def stats(self) -> dict[str, int]:
        """返回钩子统计信息"""
        return {
            "global_before": len(self._global_before),
            "global_after": len(self._global_after),
            "tool_before": sum(len(v) for v in self._before_hooks.values()),
            "tool_after": sum(len(v) for v in self._after_hooks.values()),
            "tools_with_hooks": len(
                set(self._before_hooks.keys()) | set(self._after_hooks.keys())
            ),
        }


# ── 预定义钩子 ──


async def approval_hook(context: ToolCallContext) -> None:
    """审批门钩子：需要审批的工具阻塞执行

    写入类工具（修改简历内容）在生产环境中应接入审批对话框。
    当前为占位实现，仅记录日志，不实际阻塞。
    """
    write_tools = {"rewrite_resume", "update_module", "delete_module"}
    if context.tool_name in write_tools:
        logger = logging.getLogger("react_agent.hooks")
        logger.info(
            "工具 %s 需要审批（当前跳过）, user_id=%d",
            context.tool_name,
            context.user_id,
        )
        # 实际项目中应弹出审批对话框，等待用户确认
        # context.block("需要用户审批")  # 取消注释以启用审批阻塞


async def logging_hook(context: ToolResultContext) -> None:
    """日志钩子：记录工具执行结果摘要"""
    logger = logging.getLogger("react_agent.tools")
    status = "success" if context.success else "error"
    logger.info(
        "工具执行完成: tool=%s, status=%s, duration=%.1fms",
        context.tool_name,
        status,
        context.duration_ms,
    )


async def timeout_hook(context: ToolResultContext) -> None:
    """超时钩子：工具执行超时则终止 Agent 循环

    阈值：30 秒。超时意味着工具可能陷入死循环或外部服务无响应，
    继续循环大概率不会产出有效结果。
    """
    TIMEOUT_MS = 30000  # 30 秒
    if context.duration_ms > TIMEOUT_MS:
        context.terminate_loop(
            f"工具 {context.tool_name} 执行超时 ({context.duration_ms:.0f}ms > {TIMEOUT_MS}ms)"
        )


# ── 模块级单例 ──

# 默认钩子管理器实例，供 React Agent 循环直接使用
default_hook_manager = ToolHookManager()
