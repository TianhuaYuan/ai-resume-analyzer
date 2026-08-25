"""E2: 改写 → 字段级 diff 审阅队列服务。

改写类工具（rewrite_star / translate / rewrite_resume）落库后，在落库处
附加 PendingChange 记录（不改工具 execute 内部核心逻辑）：由
`build_resume_diff(before_modules, after_modules)` 按模块字段级 diff 生成
{before, after, rationale} 记录，持久化到 pending_changes 表，前端逐条接受/丢弃。

设计（Magic-Resume diffResumeToChanges 对照）：
- 条目按 id 匹配（改写工具保留条目 id），只 diff 双方都存在的条目字段
- 富文本字段（description/summary）为主要审阅对象
- rationale 由工具名/语言/岗位派生（确定性，无需 LLM 额外输出）
"""

from __future__ import annotations

import copy
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from models.pending_change import PendingChange
from schemas.resume_edit import (
    ResumeEditError,
    modules_list_to_map,
)
from services.resume_builder import get_resume_with_modules

logger = logging.getLogger(__name__)

# 工具名 → 默认审阅理由（工具无上下文时的确定性兜底）
_DEFAULT_RATIONALE: dict[str, str] = {
    "rewrite_star": "STAR 法则改写经历描述",
    "translate": "翻译为指定语言",
    "rewrite_resume": "按目标岗位优化整份简历",
}

_CHANGE_STATUS = ("pending", "accepted", "rejected")


class PendingChangeOut(BaseModel):
    """PendingChange API 响应模型。"""

    id: int
    resume_id: int
    tool_name: str
    module_type: str
    field_path: str
    before: object | None = None
    after: object | None = None
    rationale: str = ""
    status: str = "pending"
    created_at: datetime

    model_config = {"from_attributes": True}


class PendingChangeListResponse(BaseModel):
    items: list[PendingChangeOut]
    total: int


def _tool_rationale(tool_name: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    return _DEFAULT_RATIONALE.get(tool_name, "")


# ═══════════════════════════════════════════════════════════
# 1. 纯函数：字段级 diff（不依赖 DB，便于单测）
# ═══════════════════════════════════════════════════════════


def _find_item_index(items: list, item_id: str) -> int | None:
    for i, it in enumerate(items):
        if isinstance(it, dict) and str(it.get("id", "")) == item_id:
            return i
    return None


def _diff_scalar(
    module_type: str,
    field_key: str,
    before_val,
    after_val,
    *,
    tool_name: str,
    rationale: str,
) -> dict | None:
    """比较单个标量字段，变化则产出 change dict（null 跳过 no-op）。"""
    if before_val == after_val:
        return None
    if before_val is None and after_val is None:
        return None
    return {
        "tool_name": tool_name,
        "module_type": module_type,
        "field_path": field_key,
        "before": before_val,
        "after": after_val,
        "rationale": rationale,
    }


def _diff_items(
    module_type: str,
    before_items: list,
    after_items: list,
    *,
    tool_name: str,
    rationale: str,
) -> list[dict]:
    """条目级 diff：按 id 匹配，逐字段比较。"""
    changes: list[dict] = []
    before_map = {
        str(it.get("id", "")): it for it in before_items if isinstance(it, dict) and it.get("id")
    }
    after_map = {
        str(it.get("id", "")): it for it in after_items if isinstance(it, dict) and it.get("id")
    }

    for item_id in sorted(set(before_map) | set(after_map)):
        b_item = before_map.get(item_id)
        a_item = after_map.get(item_id)
        if b_item is None:
            changes.append(
                {
                    "tool_name": tool_name,
                    "module_type": module_type,
                    "field_path": f"items.{item_id}",
                    "before": None,
                    "after": a_item,
                    "rationale": rationale,
                }
            )
            continue
        if a_item is None:
            changes.append(
                {
                    "tool_name": tool_name,
                    "module_type": module_type,
                    "field_path": f"items.{item_id}",
                    "before": b_item,
                    "after": None,
                    "rationale": rationale,
                }
            )
            continue
        # 双方都存在：逐字段 diff（跳过 id / hidden 结构字段）
        for key in sorted(set(b_item) | set(a_item)):
            if key in ("id", "hidden"):
                continue
            change = _diff_scalar(
                module_type,
                f"items.{item_id}.{key}",
                b_item.get(key),
                a_item.get(key),
                tool_name=tool_name,
                rationale=rationale,
            )
            if change:
                changes.append(change)
    return changes


def _diff_module_content(
    module_type: str,
    before: dict,
    after: dict,
    *,
    tool_name: str,
    rationale: str,
) -> list[dict]:
    """单模块 content 字段级 diff（平铺字段 + metadata + items）。"""
    changes: list[dict] = []

    # metadata（标题/隐藏）
    b_meta = before.get("metadata") if isinstance(before.get("metadata"), dict) else {}
    a_meta = after.get("metadata") if isinstance(after.get("metadata"), dict) else {}
    if b_meta.get("title") != a_meta.get("title") and (b_meta.get("title") or a_meta.get("title")):
        changes.append(
            {
                "tool_name": tool_name,
                "module_type": module_type,
                "field_path": "metadata.title",
                "before": b_meta.get("title"),
                "after": a_meta.get("title"),
                "rationale": rationale,
            }
        )

    # 平铺标量字段（排除 items / metadata / 结构字段）
    skip = {"items", "metadata", "entries", "categories"}
    for key in sorted(set(before) | set(after)):
        if key in skip:
            continue
        change = _diff_scalar(
            module_type,
            key,
            before.get(key),
            after.get(key),
            tool_name=tool_name,
            rationale=rationale,
        )
        if change:
            changes.append(change)

    # items 列表
    b_items = before.get("items") if isinstance(before.get("items"), list) else []
    a_items = after.get("items") if isinstance(after.get("items"), list) else []
    if b_items or a_items:
        changes.extend(
            _diff_items(
                module_type,
                b_items,
                a_items,
                tool_name=tool_name,
                rationale=rationale,
            )
        )

    return changes


def build_resume_diff(
    before_modules: list[dict],
    after_modules: list[dict],
    tool_name: str = "",
    rationale: str | None = None,
) -> list[dict]:
    """按模块字段级 diff 计算 PendingChange 记录（纯函数）。

    Args:
        before_modules: 改写前模块列表 [{module_type, content, ...}]
        after_modules:  改写后模块列表
        tool_name: 产生改动的工具名（rewrite_star/translate/rewrite_resume）
        rationale: 审阅理由（默认按工具名派生）

    Returns:
        [{tool_name, module_type, field_path, before, after, rationale}, ...]
        整模块新增/删除也产出记录（field_path=""，before/after 为整模块）。
    """
    reason = _tool_rationale(tool_name, rationale)
    try:
        before_map = modules_list_to_map(before_modules)
        after_map = modules_list_to_map(after_modules)
    except ResumeEditError:
        return []

    changes: list[dict] = []
    for mt in sorted(set(before_map) | set(after_map)):
        b = before_map.get(mt)
        a = after_map.get(mt)
        if b is None:
            changes.append(
                {
                    "tool_name": tool_name,
                    "module_type": mt,
                    "field_path": "",
                    "before": None,
                    "after": a,
                    "rationale": reason,
                }
            )
            continue
        if a is None:
            changes.append(
                {
                    "tool_name": tool_name,
                    "module_type": mt,
                    "field_path": "",
                    "before": b,
                    "after": None,
                    "rationale": reason,
                }
            )
            continue
        if b == a:
            continue
        changes.extend(
            _diff_module_content(mt, b, a, tool_name=tool_name, rationale=reason)
        )
    return changes


# ═══════════════════════════════════════════════════════════
# 2. 还原逻辑（reject 时把字段恢复为 before）
# ═══════════════════════════════════════════════════════════


def apply_revert(content: dict, field_path: str, before, after) -> dict:
    """把当前模块 content 中 field_path 处还原为 before。

    纯函数；返回新 dict（不修改入参）。
    - before=None（原为新增）：删除该字段/条目
    - after=None（原为删除）：恢复 before 值/条目
    - 两者都有（修改）：字段置为 before
    """
    result = copy.deepcopy(content)
    segs = field_path.split(".") if field_path else []

    if segs and segs[0] == "items":
        if len(segs) < 2:
            return result
        item_id = segs[1]
        items = result.get("items")
        if not isinstance(items, list):
            return result
        idx = _find_item_index(items, item_id)

        if len(segs) == 2:
            # 整条新增/删除
            if before is None and after is not None:
                if idx is not None:
                    result["items"].pop(idx)
            elif before is not None and after is None:
                if idx is None:
                    result["items"].append(copy.deepcopy(before))
            return result

        # 条目字段（segs[2] = field）
        if idx is None:
            return result
        field = segs[2]
        if before is None:
            result["items"][idx].pop(field, None)
        else:
            result["items"][idx][field] = copy.deepcopy(before)
        return result

    # 平铺 / metadata.xxx 路径（dict 键导航）
    if not segs:
        return result  # 整模块变更不做字段还原
    node = result
    for seg in segs[:-1]:
        if not isinstance(node, dict):
            return result
        node = node.get(seg)
        if not isinstance(node, dict):
            return result
    last = segs[-1]
    if before is None:
        if isinstance(node, dict):
            node.pop(last, None)
    else:
        if isinstance(node, dict):
            node[last] = copy.deepcopy(before)
    return result


# ═══════════════════════════════════════════════════════════
# 3. 落库（改写工具在落库处附加调用；失败不阻断改写）
# ═══════════════════════════════════════════════════════════


def modules_snapshot_from_db(modules: list) -> list[dict]:
    """ResumeModule ORM 列表 → [{module_type, content}]。"""
    return [{"module_type": m.module_type, "content": m.content} for m in modules]


async def snapshot_modules(user_id: int, resume_id: int) -> list[dict]:
    """读取简历当前模块快照（best-effort，失败返回 []）。"""
    try:
        async with AsyncSessionLocal() as session:
            _, modules = await get_resume_with_modules(session, user_id, resume_id)
            return modules_snapshot_from_db(modules)
    except Exception as e:
        logger.warning("snapshot_modules 失败（忽略）: %s", e)
        return []


async def save_pending_changes(
    user_id: int,
    resume_id: int,
    before_modules: list[dict],
    after_modules: list[dict],
    tool_name: str,
    rationale: str | None = None,
) -> int:
    """改写落库后保存字段级 diff 到 pending_changes 表。

    - 新批替换旧批：删除该简历既有 pending 记录（审阅队列是一次性状态）
    - best-effort：任何 DB 异常只记日志，不阻断改写主流程
    - 归属校验失败（简历不存在）静默返回 0

    Returns:
        保存的 PendingChange 条数
    """
    changes = build_resume_diff(before_modules, after_modules, tool_name, rationale)
    if not changes:
        return 0
    try:
        async with AsyncSessionLocal() as session:
            from models.resume import Resume

            resume = await session.get(Resume, resume_id)
            if resume is None or resume.user_id != user_id:
                return 0
            # 旧批清除
            await session.execute(
                delete(PendingChange).where(
                    PendingChange.resume_id == resume_id,
                    PendingChange.user_id == user_id,
                )
            )
            now = datetime.now(timezone.utc)
            for c in changes:
                session.add(
                    PendingChange(
                        resume_id=resume_id,
                        user_id=user_id,
                        tool_name=c.get("tool_name", tool_name),
                        module_type=c.get("module_type", ""),
                        field_path=c.get("field_path", ""),
                        before=c.get("before"),
                        after=c.get("after"),
                        rationale=c.get("rationale", "") or "",
                        status="pending",
                        created_at=now,
                    )
                )
            await session.commit()
        return len(changes)
    except Exception as e:
        logger.warning("save_pending_changes 失败（忽略）: %s", e)
        return 0


# ═══════════════════════════════════════════════════════════
# 4. 查询 / 接受 / 拒绝 / 清空（user_id 隔离）
# ═══════════════════════════════════════════════════════════


async def _get_change(db: AsyncSession, user_id: int, change_id: int) -> PendingChange | None:
    result = await db.execute(
        select(PendingChange).where(
            PendingChange.id == change_id,
            PendingChange.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_pending_changes(
    db: AsyncSession, user_id: int, resume_id: int
) -> list[PendingChange]:
    result = await db.execute(
        select(PendingChange)
        .where(
            PendingChange.resume_id == resume_id,
            PendingChange.user_id == user_id,
        )
        .order_by(PendingChange.id.asc())
    )
    return list(result.scalars().all())


async def accept_pending_change(
    db: AsyncSession, user_id: int, change_id: int
) -> PendingChange:
    """确认保留该改动（status → accepted）。"""
    change = await _get_change(db, user_id, change_id)
    if change is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="待审阅改动不存在或无权访问",
        )
    if change.status == "pending":
        change.status = "accepted"
        await db.commit()
        await db.refresh(change)
    return change


async def reject_pending_change(
    db: AsyncSession, user_id: int, change_id: int
) -> PendingChange:
    """丢弃该改动：字段按 before 还原到模块 content，status → rejected。

    还原失败（条目不存在 / 校验不过）→ 422，保留 pending 供重试。
    """
    change = await _get_change(db, user_id, change_id)
    if change is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="待审阅改动不存在或无权访问",
        )
    if change.status == "rejected":
        return change
    if change.status == "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该改动已接受，无法再还原（请先清空后重新改写）",
        )

    # 还原字段 → 模块 content
    from schemas.resume_module import validate_module_content
    from services.resume_module_mutation import (
        ResumeModuleConflictError,
        load_resume_modules_for_mutation,
        lock_resume_for_module_mutation,
    )

    try:
        resume = await lock_resume_for_module_mutation(db, user_id, change.resume_id)
    except ResumeModuleConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或无权访问",
        )

    current_modules = await load_resume_modules_for_mutation(db, change.resume_id)
    module = next((m for m in current_modules if m.module_type == change.module_type), None)

    if module is not None and change.field_path:
        current = module.content if isinstance(module.content, dict) else {}
        # before 为 None（新增）也要能删字段，故不跳过；只有整模块新增(无 field_path)跳过
        reverted = apply_revert(current, change.field_path, change.before, change.after)
        if reverted != current:
            from schemas.resume_module import ModuleType

            try:
                mt = ModuleType(change.module_type)
                validate_module_content(mt, reverted)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"还原后内容校验失败：{e}",
                ) from None
            module.content = reverted

    change.status = "rejected"
    await db.commit()
    await db.refresh(change)
    return change


async def clear_pending_changes(db: AsyncSession, user_id: int, resume_id: int) -> int:
    """清空该简历的全部待审阅记录，返回删除条数。"""
    result = await db.execute(
        delete(PendingChange).where(
            PendingChange.resume_id == resume_id,
            PendingChange.user_id == user_id,
        )
    )
    await db.commit()
    return result.rowcount or 0


# ── 辅助：JD 文本哈希（I1 幂等） ──
def jd_text_hash(jd_text: str) -> str:
    return hashlib.sha256(jd_text.encode("utf-8")).hexdigest()
