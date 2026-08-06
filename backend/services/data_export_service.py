"""C3: 用户全量数据导出服务（信任合规——用户有权带走自己的数据）。

导出当前用户的全部私有数据（按 user_id 归属的表），返回结构化 JSON：
- 账户信息（不含密码哈希等敏感字段）
- 简历（含结构化模块）
- 问答历史
- 知识资产（knowledge_assets）
- 意见箱反馈 + 点赞

设计：
- 只导出 user_id 归属的数据（公共数据不导出）
- 敏感字段（password_hash / 验证码等）一律剔除
- 时间统一 ISO 格式，前端可直接下载为 JSON
"""

import csv as _csv
import io
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.feedback_like import FeedbackLike
from models.knowledge_asset import KnowledgeAsset
from models.qa_history import QAHistory
from models.resume import Resume
from models.resume_module import ResumeModule
from models.user import User
from models.user_feedback import UserFeedback

logger = logging.getLogger(__name__)


async def export_user_data(db: AsyncSession, user_id: int) -> dict:
    """导出用户全量私有数据。

    Args:
        db: 数据库 session
        user_id: 用户 ID

    Returns:
        结构化导出数据（JSON 可序列化）
    """
    user = await db.get(User, user_id)

    # ── 账户信息（剔除敏感字段）──
    account = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": _iso(user.created_at),
    }

    # ── 简历 + 结构化模块 ──
    resumes = (
        await db.execute(select(Resume).where(Resume.user_id == user_id))
    ).scalars().all()
    resume_ids = [r.id for r in resumes]
    modules_by_resume: dict[int, list] = {}
    if resume_ids:
        modules = (
            await db.execute(
                select(ResumeModule)
                .where(ResumeModule.resume_id.in_(resume_ids))
                .order_by(ResumeModule.resume_id, ResumeModule.sort_order)
            )
        ).scalars().all()
        for m in modules:
            modules_by_resume.setdefault(m.resume_id, []).append(
                {
                    "module_type": m.module_type,
                    "content": m.content,
                    "sort_order": m.sort_order,
                }
            )
    resume_data = [
        {
            "id": r.id,
            "filename": r.filename,
            "source": r.source,
            "status": r.status,
            "created_at": _iso(r.created_at),
            "updated_at": _iso(r.updated_at),
            "modules": modules_by_resume.get(r.id, []),
        }
        for r in resumes
    ]

    # ── 问答历史 ──
    qa_history = (
        await db.execute(
            select(QAHistory).where(QAHistory.user_id == user_id).order_by(QAHistory.id)
        )
    ).scalars().all()
    qa_data = [
        {
            "id": q.id,
            "resume_id": q.resume_id,
            "question": q.question,
            "answer": q.answer,
            "created_at": _iso(q.created_at),
        }
        for q in qa_history
    ]

    # ── 知识资产 ──
    assets = (
        await db.execute(select(KnowledgeAsset).where(KnowledgeAsset.user_id == user_id))
    ).scalars().all()
    asset_data = [_serialize_row(a) for a in assets]

    # ── 意见箱反馈 + 点赞 ──
    feedbacks = (
        await db.execute(select(UserFeedback).where(UserFeedback.user_id == user_id))
    ).scalars().all()
    feedback_data = [_serialize_row(f) for f in feedbacks]

    likes = (
        await db.execute(select(FeedbackLike).where(FeedbackLike.user_id == user_id))
    ).scalars().all()
    like_data = [_serialize_row(l) for l in likes]

    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": account,
        "resumes": resume_data,
        "qa_history": qa_data,
        "knowledge_assets": asset_data,
        "feedback": feedback_data,
        "feedback_likes": like_data,
    }


def _serialize_row(obj) -> dict:
    """ORM 对象 → 字典（时间转 ISO，跳过 None 外键等）。"""
    result = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        result[column.name] = value
    return result


def _iso(value) -> str | None:
    return value.isoformat() if value else None


# ═══════════════════════════════════════════════════════════
# 导出增强（fieldwork exportData.ts 对照）：CSV 全打平 + Markdown 摘要
# 简历模块（resume_modules）全字段平铺为长表；Markdown 给人读的摘要。
# ═══════════════════════════════════════════════════════════


def _list_modules(modules: list[dict]) -> list[dict]:
    """含 items 数组的模块（长表拆行用）。"""
    return [m for m in modules if isinstance(m.get("content"), dict) and isinstance(m["content"].get("items"), list)]


def _flat_fields(content: dict) -> dict:
    """平铺模块标量字段（排除 items/metadata/entries/categories）。"""
    skip = {"items", "metadata", "entries", "categories"}
    return {k: v for k, v in content.items() if k not in skip}


def _csv_value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _csv_row(values: list) -> str:
    buf = io.StringIO()
    writer = _csv.writer(buf, lineterminator="\n")
    writer.writerow([_csv_value(v) for v in values])
    return buf.getvalue()


async def build_resume_csv(db: AsyncSession, user_id: int) -> str:
    """简历模块全字段 CSV 长表导出（fieldwork 全打平对照）。

    - 每份简历一行「平铺字段」（basic_info 等非列表模块，列名带 module_type 前缀）
    - 每个列表模块（education/work_experience/skills/...）的每条 item 单独成行，
      所有 item 字段平铺为列（模块类型列消歧）
    - 空简历也占一行（module_type 列为空），保证 Excel/Sheets 直接打开
    """
    resumes = (await db.execute(select(Resume).where(Resume.user_id == user_id))).scalars().all()
    resume_ids = [r.id for r in resumes]
    modules_by_resume: dict[int, list[dict]] = {}
    if resume_ids:
        mods = (
            await db.execute(
                select(ResumeModule)
                .where(ResumeModule.resume_id.in_(resume_ids))
                .order_by(ResumeModule.resume_id, ResumeModule.sort_order)
            )
        ).scalars().all()
        for m in mods:
            modules_by_resume.setdefault(m.resume_id, []).append(
                {"module_type": m.module_type, "content": m.content}
            )

    # 全表 item 字段并集（列头）
    all_item_fields: set[str] = set()
    for rmods in modules_by_resume.values():
        for m in _list_modules(rmods):
            for it in m["content"].get("items", []):
                if isinstance(it, dict):
                    all_item_fields.update(k for k in it if k not in ("id", "hidden"))

    # 平铺字段并集（列头，带 module_type 前缀）；列表模块（含 items）不参与平铺
    list_types: set[str] = set()
    for rmods in modules_by_resume.values():
        list_types.update(m["module_type"] for m in _list_modules(rmods))

    flat_header: list[str] = []
    for rmods in modules_by_resume.values():
        for m in rmods:
            if m["module_type"] in list_types:
                continue
            for k in _flat_fields(m["content"]):
                col = f"{m['module_type']}.{k}"
                if col not in flat_header:
                    flat_header.append(col)

    item_field_list = sorted(all_item_fields)
    header = (
        ["resume_id", "filename", "status", "source", "created_at", "updated_at"]
        + flat_header
        + ["module_type", "item_index"]
        + item_field_list
        + ["item_json"]
    )

    out = [_csv_row(header)]
    for r in resumes:
        rmods = modules_by_resume.get(r.id, [])
        flat_map: dict[str, str] = {}
        list_mods: list[dict] = []
        for m in rmods:
            if m["module_type"] in list_types:
                list_mods.append(m)
            else:
                for k, v in _flat_fields(m["content"]).items():
                    flat_map[f"{m['module_type']}.{k}"] = _csv_value(v)

        def _base_row() -> list:
            return [
                r.id,
                r.filename,
                r.status,
                r.source,
                _iso(r.created_at),
                _iso(r.updated_at),
            ] + [flat_map.get(c, "") for c in flat_header]

        # 长表拆行：每条 item 一行；无列表条目也占一行
        if not list_mods:
            out.append(_csv_row(_base_row() + ["", ""] + ["" for _ in item_field_list] + [""]))
            continue
        for m in list_mods:
            items = m["content"].get("items", [])
            if not items:
                out.append(
                    _csv_row(_base_row() + [m["module_type"], ""] + ["" for _ in item_field_list] + ["{}"])
                )
                continue
            for idx, it in enumerate(items):
                if not isinstance(it, dict):
                    it = {"value": it}
                item_vals = [_csv_value(it.get(f)) for f in item_field_list]
                out.append(
                    _csv_row(
                        _base_row()
                        + [m["module_type"], idx]
                        + item_vals
                        + [json.dumps(it, ensure_ascii=False)]
                    )
                )
    return "".join(out)


async def build_resume_markdown(db: AsyncSession, user_id: int) -> str:
    """简历 Markdown 摘要导出（fieldwork buildApplicationsMarkdown 对照）。

    给人读的概览：每份简历 → 基本信息/教育/工作/技能等模块条目摘要，
    与 CSV 长表互补（不是它的重复）。
    """
    from schemas.resume_module import DEFAULT_MODULE_LABELS, get_content_title

    resumes = (await db.execute(select(Resume).where(Resume.user_id == user_id))).scalars().all()
    resume_ids = [r.id for r in resumes]
    modules_by_resume: dict[int, list] = {}
    if resume_ids:
        mods = (
            await db.execute(
                select(ResumeModule)
                .where(ResumeModule.resume_id.in_(resume_ids))
                .order_by(ResumeModule.resume_id, ResumeModule.sort_order)
            )
        ).scalars().all()
        for m in mods:
            modules_by_resume.setdefault(m.resume_id, []).append(m)

    total_modules = sum(len(v) for v in modules_by_resume.values())
    lines = [
        f"# 简历数据导出 — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        f"共 {len(resumes)} 份简历，{total_modules} 个模块。",
        "",
    ]
    for r in resumes:
        lines.append(f"## {r.filename}（ID: {r.id}）")
        lines.append(f"- 状态：{r.status} · 来源：{r.source} · 更新：{_iso(r.updated_at) or '-'}")
        mods = modules_by_resume.get(r.id, [])
        if not mods:
            lines.append("- （无模块内容）")
            lines.append("")
            continue
        for m in mods:
            title = get_content_title(m.content, m.module_type)
            lines.append(f"### {title}")
            content = m.content if isinstance(m.content, dict) else {}
            items = content.get("items") if isinstance(content.get("items"), list) else []
            if items:
                for it in items:
                    if not isinstance(it, dict):
                        lines.append(f"- {it}")
                        continue
                    head = (
                        it.get("name") or it.get("company") or it.get("school")
                        or it.get("title") or "条目"
                    )
                    when = (
                        f"（{it.get('start_date', '') or ''} - {it.get('end_date', '') or ''}）"
                        if it.get("start_date") or it.get("end_date")
                        else ""
                    )
                    desc = str(it.get("description") or it.get("summary") or "")
                    line = f"- **{head}**{when}"
                    if desc:
                        line += f"：{desc[:200]}"
                    lines.append(line)
            else:
                # 平铺模块（basic_info 等）：列非空标量
                flat = _flat_fields(content)
                flat_text = "，".join(f"{k}: {v}" for k, v in flat.items() if v not in (None, ""))
                lines.append(f"- {flat_text or '（空）'}")
        lines.append("")

    return "\n".join(lines)
