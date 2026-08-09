"""记忆提供者接口 — 记忆系统可扩展抽象（借鉴 Hermes MemoryProvider）。

现状：memory.py 的 L1-L4 记忆装配是散落的独立函数
（assemble_system_prompt / get_l2_history / get_l3_profile / recall_with_entity_boost）。
本模块定义 MemoryProvider 协议 + 默认实现，把"记忆读写"收敛为统一接口，
便于后续：
- 替换记忆后端（Redis → 向量库 / 混合存储）而不动 loop 调用方
- 记忆预取（prefetch_all 提前加载）/ 后台同步（queue_sync_all）

注意：默认实现包装现有 memory.py 函数（不重写逻辑），
作为抽象层供 loop/工具按协议调用，保证向后兼容。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass
class MemoryContext:
    """聚合记忆上下文（prefetch_all 的返回）。"""

    l2_history: list[dict] = field(default_factory=list)  # 情景记忆（最近问答）
    l3_profile: dict[str, Any] = field(default_factory=dict)  # 语义记忆（画像）
    l4_recall: list[dict] = field(default_factory=list)  # 长期记忆召回
    system_blocks: list[str] = field(default_factory=list)  # 已渲染的系统提示块


class MemoryProvider(Protocol):
    """记忆提供者协议（借鉴 Hermes MemoryProvider）。

    方法：
    - prefetch_all(user_id, resume_id, question) → MemoryContext：一次取齐 L2/L3/L4
    - build_system_prompt(db, ctx, user_id, resume_id, *, tool_mode) → str：
      由聚合上下文渲染系统提示（需 db/user/resume 供 assemble_system_prompt）
    - queue_sync_all(...)：后台异步同步记忆（默认 no-op）
    """

    async def prefetch_all(
        self, user_id: int, resume_id: int, question: str
    ) -> MemoryContext: ...

    def build_system_prompt(
        self,
        db: Any,
        ctx: MemoryContext,
        user_id: int,
        resume_id: int,
        *,
        tool_mode: str = "agent",
    ) -> str: ...

    async def queue_sync_all(
        self, user_id: int, resume_id: int, question: str, answer: str
    ) -> None: ...


class DefaultMemoryProvider:
    """默认记忆提供者：包装现有 memory.py 函数（不重写逻辑）。

    - prefetch_all：并行取 L2 历史 + L3 画像 + L4 召回（失败项降级为空）
    - build_system_prompt：委托 memory.assemble_system_prompt
    - queue_sync_all：默认 no-op（L4 记忆提炼由现有 extraction_trigger 后台处理）
    """

    async def prefetch_all(
        self, user_id: int, resume_id: int, question: str
    ) -> MemoryContext:
        from services.react_agent import memory as mem

        ctx = MemoryContext()
        # 并行取 L2/L3/L4，单项失败不影响整体
        try:
            ctx.l2_history = await mem.get_l2_history(
                user_id, resume_id, exclude_questions=[question]
            )
        except Exception as e:
            logger.debug("L2 历史预取失败（降级为空）: %s", e)
        try:
            ctx.l3_profile = await mem.get_l3_profile(resume_id) or {}
        except Exception as e:
            logger.debug("L3 画像预取失败（降级为空）: %s", e)
        try:
            ctx.l4_recall = await mem.recall_with_entity_boost(
                resume_id, question
            )
        except Exception as e:
            logger.debug("L4 召回预取失败（降级为空）: %s", e)
        return ctx

    def build_system_prompt(
        self,
        db: Any,
        ctx: MemoryContext,
        user_id: int,
        resume_id: int,
        *,
        tool_mode: str = "agent",
    ) -> str:
        from services.react_agent import memory as mem

        return mem.assemble_system_prompt(
            db=db,
            user_id=user_id,
            resume_id=resume_id,
            builder=(tool_mode == "builder"),
        )

    async def queue_sync_all(
        self, user_id: int, resume_id: int, question: str, answer: str
    ) -> None:
        # 现有 extraction_trigger 已在流结束后台处理 L4 提炼，这里 no-op 保持接口
        return None
