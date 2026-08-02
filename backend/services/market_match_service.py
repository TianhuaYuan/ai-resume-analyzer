"""市场岗位匹配推荐服务。

策略（廉价召回 + 精准精排）：
  1. prefilter_jobs：简历文本向量化 → 在公共集合 market_public 按 asset_type=job 预筛 top N（向量检索，零 LLM）
  2. score_job_for_resume：对 top K 逐个 LLM 评分（匹配分/匹配点/差距/理由）
  3. recommend_jobs：按分排序返回结构化结果（过期岗位在 DB 回表时过滤）

复用：get_embeddings / build_asset_where / VectorStore.query / llm_generate（走 token 配额）。
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.retry import with_retry
from models.market_asset import MarketAsset
from models.resume import Resume
from services.rag.clients import market_collection_name
from services.rag.pipeline import llm_generate
from services.rag.retrieval import build_asset_where, get_embeddings
from services.vector_store import get_vector_store

logger = logging.getLogger(__name__)

_PREFILTER_TOP_N = 30   # 向量预筛召回数
_SCORE_TOP_K = 5        # LLM 精排岗位数
_RESUME_TEXT_LIMIT = 4000
_JD_TEXT_LIMIT = 3000

_SYSTEM_PROMPT = (
    "你是专业的招聘匹配分析师。根据候选人的简历与目标岗位 JD，"
    "评估候选人与此岗位的匹配程度。输出必须是纯 JSON，不要包含任何其他文字。"
)


def _build_score_user_prompt(resume_text: str, asset: MarketAsset) -> str:
    jd_parts = [
        asset.title or "",
        asset.company or "",
        asset.position or "",
        asset.city or "",
        asset.salary or "",
        asset.degree or "",
        asset.content[: _JD_TEXT_LIMIT],
    ]
    jd = "\n".join(p for p in jd_parts if p)
    return (
        f"候选人简历：\n{resume_text[: _RESUME_TEXT_LIMIT]}\n\n"
        f"目标岗位：\n{jd}\n\n"
        "请输出 JSON（不要用 Markdown 代码块）：\n"
        '{"score": 0到100的整数, "matched": ["匹配点1","匹配点2"], '
        '"gaps": ["差距1","差距2"], "reason": "一句话理由"}'
    )


def _parse_score(text: str) -> dict:
    """解析 LLM 评分输出，防御性降级：非 JSON / 缺字段时返回默认分。"""
    if not text:
        return {"score": 0, "matched": [], "gaps": [], "reason": ""}
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        # 去掉可能的 Markdown 代码块围栏后重试
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            data = json.loads(cleaned.strip())
        except (json.JSONDecodeError, IndexError):
            logger.warning("recommend score parse failed, fallback: %.40s", text[:40])
            return {"score": 50, "matched": [], "gaps": [], "reason": text[:200]}

    if not isinstance(data, dict):
        return {"score": 50, "matched": [], "gaps": [], "reason": ""}
    try:
        score = int(data.get("score", 50))
        score = max(0, min(100, score))
    except (TypeError, ValueError):
        score = 50
    return {
        "score": score,
        "matched": data.get("matched") or [],
        "gaps": data.get("gaps") or [],
        "reason": (data.get("reason") or "")[:200],
    }


async def prefilter_jobs(
    db: AsyncSession,
    resume_text: str,
    *,
    job_type: str | None = None,
    top_n: int = _PREFILTER_TOP_N,
) -> list[MarketAsset]:
    """向量预筛：简历文本 → market_public 检索 job 资产 → DB 回表过滤过期/类型。"""
    if not resume_text.strip():
        return []
    embedding = (await get_embeddings([resume_text]))[0]
    where = build_asset_where("job")
    items = await get_vector_store().query(
        market_collection_name(), embedding, top_n, where=where
    )
    if not items:
        return []
    asset_ids = [int(it["metadata"]["asset_id"]) for it in items if it.get("metadata")]
    if not asset_ids:
        return []

    conditions = [MarketAsset.id.in_(asset_ids), MarketAsset.is_expired == False]  # noqa: E712
    if job_type:
        conditions.append(MarketAsset.job_type == job_type)
    result = await db.execute(
        select(MarketAsset).where(*conditions).order_by(MarketAsset.id)
    )
    rows = result.scalars().all()
    # 保持向量检索的召回顺序（id → 原顺序）
    order = {aid: i for i, aid in enumerate(asset_ids)}
    return sorted(rows, key=lambda r: order.get(r.id, len(asset_ids)))


async def score_job_for_resume(
    resume_text: str,
    asset: MarketAsset,
    *,
    user_id: int,
) -> dict[str, Any]:
    """单岗位 LLM 评分（复用 llm_generate，走用户 token 配额）。"""
    try:
        text = await with_retry(
            llm_generate,
            _SYSTEM_PROMPT,
            _build_score_user_prompt(resume_text, asset),
            temperature=0.1,
            max_tokens=600,
            user_id=user_id,
            fallback="",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("score job failed asset=%s: %s", asset.id, e)
        text = ""
    parsed = _parse_score(text)
    return {
        "id": asset.id,
        "title": asset.title,
        "company": asset.company,
        "position": asset.position,
        "city": asset.city,
        "salary": asset.salary,
        "job_type": asset.job_type,
        **parsed,
    }


async def recommend_jobs(
    db: AsyncSession,
    *,
    user_id: int,
    resume_id: int,
    top_k: int = _SCORE_TOP_K,
    job_type: str | None = None,
) -> list[dict[str, Any]]:
    """基于简历推荐匹配岗位。

    Raises:
        HTTPException: 404 简历不存在/非本人；409 简历未就绪；422 简历内容为空
    """
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="简历不存在或无权访问",
        )
    if resume.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"简历未就绪（当前状态: {resume.status}）",
        )
    resume_text = (resume.parsed_text or "").strip()
    if not resume_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="简历内容为空",
        )

    candidates = await prefilter_jobs(db, resume_text, job_type=job_type)
    if not candidates:
        return []

    scored = await asyncio.gather(
        *[
            score_job_for_resume(resume_text, a, user_id=user_id)
            for a in candidates[: max(top_k, _SCORE_TOP_K)]
        ]
    )
    scored.sort(key=lambda s: s.get("score", 0), reverse=True)
    return scored[:top_k]
