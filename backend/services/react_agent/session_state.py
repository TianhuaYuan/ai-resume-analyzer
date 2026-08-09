"""
会话状态机系统 -- 三态追踪 + 工具调用历史

借鉴 OpenClaw 的 Session Tree + 状态机设计：
- 三态：idle -> processing -> waiting -> processing -> idle
- 工具调用历史：记录最近 20 次调用
- 自动清理：TTL 过期 + 容量限制

使用场景：
1. Agent 开始处理时：transition(PROCESSING)
2. Agent 等待工具时：transition(WAITING)
3. Agent 完成时：transition(IDLE)
4. 查询会话状态：get_state()
5. 记录工具调用：record_tool_call()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class SessionStateType(str, Enum):
    """会话状态类型"""

    IDLE = "idle"  # 空闲
    PROCESSING = "processing"  # 处理中
    WAITING = "waiting"  # 等待工具执行


@dataclass
class ToolCallRecord:
    """工具调用记录

    记录每次工具调用的关键元信息，用于：
    1. 工具循环检测（通过 args_hash 识别重复调用）
    2. 调用链追踪（tool_call_id 关联 LLM tool_use 输出）
    3. 性能分析（duration_ms 统计耗时）
    """

    tool_name: str
    args_hash: str
    tool_call_id: str
    outcome_kind: Literal["success", "error", "tool-loop-veto"] | None = None
    result_hash: str | None = None
    timestamp: float = 0.0
    duration_ms: float = 0.0


@dataclass
class SessionState:
    """会话状态

    每个 (user_id, resume_id, conversation_id) 三元组对应一个独立的会话状态。
    状态机保证状态转换的合法性，防止并发竞争导致的非法状态。
    """

    session_id: str
    user_id: int
    resume_id: int
    state: SessionStateType = SessionStateType.IDLE
    queue_depth: int = 0
    tool_call_history: list[ToolCallRecord] = field(default_factory=list)
    last_activity: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """序列化为字典，便于日志记录和 API 返回"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "resume_id": self.resume_id,
            "state": self.state.value,
            "queue_depth": self.queue_depth,
            "tool_call_count": len(self.tool_call_history),
            "last_activity": self.last_activity,
            "created_at": self.created_at,
        }


class SessionStateMachine:
    """会话状态机：追踪会话状态 + 工具调用历史

    核心职责：
    1. 三态管理：idle / processing / waiting，严格限定转换规则
    2. 工具调用记录：保留最近 20 次调用，用于循环检测和链路追踪
    3. 自动清理：TTL 过期 + 容量上限，防止内存泄漏

    状态转换规则：
        IDLE       -> PROCESSING   （开始处理用户请求）
        PROCESSING -> WAITING      （调用工具，等待返回）
        PROCESSING -> IDLE         （处理完成，直接返回）
        WAITING    -> PROCESSING   （工具返回结果，继续处理）

    并发安全：
        所有状态读写通过 asyncio.Lock 保护，同一时刻只有一个协程修改状态。
        由于 asyncio 单线程事件循环，Lock 实际是协程级别的互斥，无 GIL 争用。
    """

    # 合法的状态转换集合：{当前状态: {允许转换的目标状态集合}}
    TRANSITIONS: dict[SessionStateType, set[SessionStateType]] = {
        SessionStateType.IDLE: {SessionStateType.PROCESSING},
        SessionStateType.PROCESSING: {SessionStateType.WAITING, SessionStateType.IDLE},
        SessionStateType.WAITING: {SessionStateType.PROCESSING},
    }

    def __init__(self, ttl_seconds: int = 1800, max_sessions: int = 2000):
        """
        Args:
            ttl_seconds: 会话过期时间（秒），默认 30 分钟无活动自动清理
            max_sessions: 最大活跃会话数，超出后触发过期清理
        """
        self.sessions: dict[str, SessionState] = {}
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._lock = asyncio.Lock()

    @staticmethod
    def _generate_session_key(
        user_id: int,
        resume_id: int,
        conversation_id: str | None = None,
    ) -> str:
        """生成会话唯一 key

        格式：{user_id}:{resume_id}:{conversation_id}
        同一用户对同一简历的不同对话有独立的状态追踪。
        """
        conv = conversation_id or "default"
        return f"{user_id}:{resume_id}:{conv}"

    async def get_or_create(
        self,
        user_id: int,
        resume_id: int,
        conversation_id: str | None = None,
    ) -> SessionState:
        """获取或创建会话状态

        幂等操作：会话存在则返回现有状态，不存在则创建 IDLE 状态。
        每次调用会刷新 last_activity 时间戳。
        """
        key = self._generate_session_key(user_id, resume_id, conversation_id)

        async with self._lock:
            if key not in self.sessions:
                # 容量检查：超出上限时先清理过期会话
                if len(self.sessions) >= self.max_sessions:
                    await self._evict_expired()

                self.sessions[key] = SessionState(
                    session_id=key,
                    user_id=user_id,
                    resume_id=resume_id,
                )

            session = self.sessions[key]
            session.last_activity = time.time()
            return session

    async def transition(
        self,
        user_id: int,
        resume_id: int,
        new_state: SessionStateType,
        conversation_id: str | None = None,
    ) -> bool:
        """状态转换

        严格校验转换合法性，非法转换返回 False。
        同时维护 queue_depth 计数：
        - 进入 PROCESSING 时 +1（新请求入队）
        - 回到 IDLE 时 -1（请求处理完毕）
        """
        key = self._generate_session_key(user_id, resume_id, conversation_id)

        async with self._lock:
            session = self.sessions.get(key)
            if not session:
                return False

            # 检查转换是否合法
            allowed = self.TRANSITIONS.get(session.state, set())
            if new_state not in allowed:
                return False

            old_state = session.state
            session.state = new_state
            session.last_activity = time.time()

            # 维护队列深度
            if new_state == SessionStateType.PROCESSING:
                session.queue_depth += 1
            elif new_state == SessionStateType.IDLE and old_state == SessionStateType.PROCESSING:
                session.queue_depth = max(0, session.queue_depth - 1)

            return True

    async def record_tool_call(
        self,
        user_id: int,
        resume_id: int,
        record: ToolCallRecord,
        conversation_id: str | None = None,
    ) -> None:
        """记录工具调用到会话历史

        保留最近 20 条记录，超出后 FIFO 淘汰最旧的。
        用于：
        1. tool_gate 的循环检测（对比 args_hash）
        2. 调试时查看完整工具调用链
        """
        key = self._generate_session_key(user_id, resume_id, conversation_id)

        async with self._lock:
            session = self.sessions.get(key)
            if session:
                session.tool_call_history.append(record)
                session.last_activity = time.time()
                # 保留最近 20 条
                if len(session.tool_call_history) > 20:
                    session.tool_call_history = session.tool_call_history[-20:]

    async def get_state(
        self,
        user_id: int,
        resume_id: int,
        conversation_id: str | None = None,
    ) -> SessionState | None:
        """获取会话状态（只读）

        不存在时返回 None，不创建新会话。
        """
        key = self._generate_session_key(user_id, resume_id, conversation_id)
        return self.sessions.get(key)

    async def get_active_count(self) -> int:
        """获取当前活跃会话数"""
        return len(self.sessions)

    async def get_stats(self) -> dict:
        """获取状态机统计信息，便于监控"""
        async with self._lock:
            state_counts: dict[str, int] = {}
            for session in self.sessions.values():
                s = session.state.value
                state_counts[s] = state_counts.get(s, 0) + 1
            return {
                "total_sessions": len(self.sessions),
                "state_counts": state_counts,
                "ttl_seconds": self.ttl_seconds,
                "max_sessions": self.max_sessions,
            }

    async def _evict_expired(self) -> int:
        """清理过期会话

        删除所有 last_activity 超过 TTL 的会话。
        返回清理的数量。
        """
        now = time.time()
        expired_keys = [
            k
            for k, v in self.sessions.items()
            if now - v.last_activity > self.ttl_seconds
        ]
        for k in expired_keys:
            del self.sessions[k]
        return len(expired_keys)

    async def cleanup(self) -> int:
        """定期清理（建议后台定时调用）

        返回本次清理的过期会话数。
        """
        async with self._lock:
            return await self._evict_expired()
