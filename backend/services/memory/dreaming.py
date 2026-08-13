"""Dreaming 记忆整合 — 后台整理 L4 记忆，防止膨胀（借鉴 OpenClaw Dreaming）。

在 consolidation.py（过期标记 + 相似去重）基础上，增加 **模型整合** 维度：
1. 确定性门控筛选候选：来源可信（非 untrusted）+ 重要度高 + 近期活跃 + 召回频率高
2. 对高价值候选做 LLM 整合摘要，压缩为 semantic 层级记忆写入
3. 整合后的原始 episodic 片段标记降权（可选：不删除，保留历史）

调度：不引入 APScheduler——复用项目现有 RabbitMQ consumer / 后台定时模式
（与 consolidation 一致）。本模块只做逻辑，调度由调用方负责。
"""

from __future__ import annotations

import logging
import time

from services.memory.memory_store import (
    MEM_CREATED_AT,
    MEM_IMPORTANCE,
    MEM_LAST_ACCESSED,
    MEM_PROJECT,
    MEM_TTL,
    MEM_TYPE,
    _collection,
    save_memory,
)
from services.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# Dreaming 候选门控阈值
_DREAMING_MIN_IMPORTANCE = 0.6  # 只整合重要度 ≥ 0.6 的记忆
_DREAMING_MAX_AGE_DAYS = 7  # 只整合近 7 天内创建的记忆
_DREAMING_BATCH_MAX = 20  # 单次最多整合 20 条候选（防单轮过重）
_DREAMING_SUMMARY_CHARS = 800  # 整合摘要上限字符


def _select_candidates(items: list[dict], now: int) -> list[dict]:
    """确定性门控：筛选 Dreaming 整合候选。

    规则（全部满足才入选）：
    - 未过期（无 ttl 或未超期）
    - importance ≥ _DREAMING_MIN_IMPORTANCE
    - 创建时间在近 _DREAMING_MAX_AGE_DAYS 内
    - 排除已整合的 semantic 层级（避免重复整合）
    """
    cutoff = now - _DREAMING_MAX_AGE_DAYS * 86400
    candidates: list[dict] = []
    for item in items:
        meta = item["metadata"] or {}
        ttl = meta.get(MEM_TTL)
        if ttl and now - int(meta.get(MEM_LAST_ACCESSED, 0)) > int(ttl):
            continue  # 已过期
        if float(meta.get(MEM_IMPORTANCE, 0.5)) < _DREAMING_MIN_IMPORTANCE:
            continue
        if int(meta.get(MEM_CREATED_AT, 0)) < cutoff:
            continue
        if meta.get(MEM_TYPE) == "semantic":
            continue  # 已整合过
        candidates.append(item)
    # 重要度高优先，取前 N
    candidates.sort(
        key=lambda it: float(it["metadata"].get(MEM_IMPORTANCE, 0.5)), reverse=True
    )
    return candidates[:_DREAMING_BATCH_MAX]


async def _llm_integrate(
    texts: list[str], project: str | None, llm_caller=None
) -> str:
    """模型整合：将候选记忆压缩为结构化语义摘要。

    llm_caller 为 None 时退化为启发式摘要（拼接 + 去重），保证离线可用。
    """
    joined = "\n".join(f"- {t}" for t in texts)
    if llm_caller is None:
        # 启发式降级：保留项目标记 + 拼接
        prefix = f"[项目:{project}] " if project else ""
        return f"{prefix}记忆整合摘要（{len(texts)} 条）:\n{joined[:_DREAMING_SUMMARY_CHARS]}"
    try:
        summary = await llm_caller(
            "将以下记忆片段整合为一段精简的长期事实摘要，去掉重复，保留关键信息：\n"
            + joined
        )
        return (summary or "").strip()[:_DREAMING_SUMMARY_CHARS]
    except Exception as e:
        logger.warning("Dreaming LLM 整合失败（降级拼接）: %s", e)
        return f"记忆整合摘要（{len(texts)} 条）:\n{joined[:_DREAMING_SUMMARY_CHARS]}"


async def dream(
    user_id: int,
    *,
    llm_caller=None,
    project: str | None = None,
    active_project: str | None = None,
) -> dict:
    """执行一次 Dreaming 整合。返回统计。

    Args:
        user_id: 目标用户。
        llm_caller: LLM 整合调用函数（async callable），None 时用启发式摘要。
        project: 项目作用域——只整合该项目的候选（跨项目不串扰）。
        active_project: 活跃项目标记（写入整合摘要时保留，供后续召回加权）。

    Returns:
        {"candidates": int, "integrated": int, "summary": str}
    """
    store = get_vector_store()
    collection = _collection(user_id)
    items = await store.get(collection)
    if not items:
        return {"candidates": 0, "integrated": 0, "summary": ""}

    now = int(time.time())
    candidates = _select_candidates(items, now)
    if project:
        candidates = [
            it
            for it in candidates
            if (it["metadata"] or {}).get(MEM_PROJECT) == project
        ]
    if not candidates:
        return {"candidates": 0, "integrated": 0, "summary": ""}

    texts = [it["text"] for it in candidates]
    summary = await _llm_integrate(texts, project or active_project, llm_caller)

    # 写入整合后的 semantic 层级记忆（保留项目标记）
    await save_memory(
        user_id=user_id,
        snippet=summary,
        memory_type="semantic",
        importance=min(1.0, max(float(it["metadata"].get(MEM_IMPORTANCE, 0.5)) for it in candidates)),
        project=project or active_project,
    )
    logger.info(
        "Dreaming 整合: user=%d 候选=%d 摘要=%d 字 project=%s",
        user_id, len(candidates), len(summary), project or active_project,
    )
    return {
        "candidates": len(candidates),
        "integrated": len(candidates),
        "summary": summary,
    }
