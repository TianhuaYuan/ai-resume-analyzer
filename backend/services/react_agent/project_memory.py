"""项目作用域记忆 — 记忆按项目标记 + 召回加权（借鉴 OpenClaw ProjectScope）。

策略（P2-13）：
- 活跃项目记忆提升（1.5x）
- 非活跃项目记忆降权（0.8x）
- 无项目标记记忆保持中性（1.0x）

用法：
    # 存储带项目标记
    await save_memory(user_id=u, snippet=s, project="resume-builder")

    # 召回按项目过滤 + 活跃项目加权
    memories = await recall_memory(
        user_id=u, query=q,
        project="resume-builder",   # 只召回该项目（或中性）记忆
        active_project="resume-builder",  # 该项目记忆加权 1.5x
    )

    # Agent 工具可据此生成"项目作用域"感知：跨项目不串扰。
"""

from __future__ import annotations

# 项目加权系数（与 memory_store.recall_memory 中的实现保持一致；若调整需同步）
PROJECT_ACTIVE_WEIGHT = 1.5
PROJECT_INACTIVE_WEIGHT = 0.8
PROJECT_NEUTRAL_WEIGHT = 1.0


def project_recall_weight(
    mem_project: str | None, active_project: str | None
) -> float:
    """计算单条记忆的项目加权系数。

    - mem_project=None → 中性 1.0（无项目标记，不参与项目加权）
    - mem_project==active_project → 活跃项目 1.5x
    - 其他 → 非活跃项目 0.8x
    """
    if not mem_project:
        return PROJECT_NEUTRAL_WEIGHT
    if active_project and mem_project == active_project:
        return PROJECT_ACTIVE_WEIGHT
    return PROJECT_INACTIVE_WEIGHT
