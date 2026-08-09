"""授权门控系统 — 工具执行权限控制（借鉴 Hermes _authorization_gate_lock_timeout）。

与 D1 审批门的分工：
- 审批门（base.py _approval_gate_active）：**逐次**确认——每次工具调用前弹窗让用户批准/拒绝
- 授权门控（本模块）：**策略级**控制——按工具名/类别配置执行权限、串行化授权
  等待、超时护栏，避免并发授权请求风暴和无限挂起。

核心能力：
1. 工具级授权策略：高代价/高副作用工具可标记为需要授权串行化（如批量联网搜索、
   整份简历重写），同一用户同时只允许一个授权等待在途
2. 授权序列化锁 + 超时：参考 Hermes _authorization_gate_lock_timeout——授权等待
   时间 = 审批超时 + 安全边距，超时自动放行（避免挂死烧 token）
3. 授权黑名单：明确禁止的工具直接拒绝（不回灌 LLM 重试，杜绝绕过）
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# 授权序列化锁超时基准（秒）：参考 Hermes _AUTHORIZATION_GATE_LOCK_TIMEOUT_S。
# 审批门超时（loop.APPROVAL_TIMEOUT_SEC=120）之上的安全边距。
_AUTHORIZATION_GATE_LOCK_TIMEOUT_S = 360.0
_AUTHORIZATION_GATE_LOCK_MARGIN_S = 30.0  # 审批超时之上的额外边距

# 工具授权分类：高代价/高副作用工具需要授权串行化（一次只有一个在途）。
# 覆盖写库类 + 外部请求类工具——与 base._APPROVAL_REQUIRED 同口径。
_AUTHORIZATION_SERIALIZED_TOOLS: frozenset[str] = frozenset(
    {
        "save_memory",
        "modify_module",
        "rewrite_resume",
        "rewrite_star",
        "translate",
        "search_jobs_live",
        "web_search",
    }
)

# 授权黑名单：明确禁止的工具。命中即拒绝执行并终止该工具路径
# （区别于 ToolRetryError——不回灌 LLM 重试，杜绝绕过尝试）。
_AUTHORIZATION_BLOCKED_TOOLS: frozenset[str] = frozenset(
    {
        # 预留：如 "system_shell" / "delete_all_data" 等高危工具
    }
)


def authorization_gate_lock_timeout() -> float:
    """授权序列化锁超时（秒）。

    参考 Hermes _authorization_gate_lock_timeout：审批超时 + 安全边距。
    从 loop.APPROVAL_TIMEOUT_SEC 读取审批超时（避免魔法数漂移），
    导入失败回退默认值。
    """
    try:
        from services.react_agent.loop import APPROVAL_TIMEOUT_SEC

        return APPROVAL_TIMEOUT_SEC + _AUTHORIZATION_GATE_LOCK_MARGIN_S
    except Exception:
        return _AUTHORIZATION_GATE_LOCK_TIMEOUT_S


class AuthorizationGate:
    """授权门控：工具级权限策略 + 序列化授权锁 + 超时护栏。

    每个 (user_id, tool_name) 一个授权槽（in-flight 集合）。高代价工具
    在途授权未结束时，新授权请求等待前一个完成（有限等待，超时放行），
    防止并发授权风暴。

    用法（loop 工具执行前）：
        gate = AuthorizationGate()
        ok, reason = await gate.authorize(user_id, tc.name, timeout=...)
        if not ok:
            # blocked → 直接拒绝回灌；awaiting → 已获得授权槽可继续
    """

    def __init__(self) -> None:
        self._inflight: set[tuple[int, str]] = set()
        self._lock: asyncio.Lock = asyncio.Lock()

    def is_blocked(self, tool_name: str) -> bool:
        """工具是否在授权黑名单（命中直接拒绝，不回灌 LLM 重试）。"""
        return tool_name in _AUTHORIZATION_BLOCKED_TOOLS

    def needs_serialization(self, tool_name: str) -> bool:
        """工具是否需要授权串行化（高代价/高副作用）。"""
        return tool_name in _AUTHORIZATION_SERIALIZED_TOOLS

    async def authorize(
        self,
        user_id: int,
        tool_name: str,
        *,
        timeout: float | None = None,
    ) -> tuple[bool, str]:
        """授权检查。返回 (allowed, reason)。

        allowed=False + reason="blocked"   → 工具被禁止，直接拒绝
        allowed=False + reason="timeout"   → 等待授权槽超时，放行（避免挂死）
        allowed=True                       → 获得授权（或无需串行化）

        注意：获得授权槽后调用方需在工具执行完成后调用 release() 释放。
        """
        # 1. 黑名单检查——明确禁止，直接拒绝
        if self.is_blocked(tool_name):
            logger.warning("授权门控拒绝: 工具 %s 在黑名单", tool_name)
            return False, "blocked"

        # 2. 非高代价工具无需串行化，直接放行
        if not self.needs_serialization(tool_name):
            return True, ""

        # 3. 高代价工具：串行化授权——等待在途授权释放（有限等待）
        slot = (user_id, tool_name)
        gate_timeout = timeout or authorization_gate_lock_timeout()
        waited = 0.0
        tick = 0.5
        while True:
            async with self._lock:
                if slot not in self._inflight:
                    self._inflight.add(slot)
                    return True, ""
            if waited >= gate_timeout:
                logger.warning(
                    "授权等待超时（%.0fs），放行: user=%d tool=%s",
                    waited, user_id, tool_name,
                )
                return True, "timeout"
            await asyncio.sleep(tick)
            waited += tick

    async def release(self, user_id: int, tool_name: str) -> None:
        """释放授权槽（工具执行完成后调用）。"""
        async with self._lock:
            self._inflight.discard((user_id, tool_name))

    def inflight_count(self) -> int:
        """当前在途授权数（诊断用）。"""
        return len(self._inflight)
