"""asset_service.py — 知识资产写入服务（职责重定位：归档来源 + 幂等 upsert）。

知识资产从「业务录入入口」收敛为「聚合检索视图」后，JD / 面试复盘内容的写入
统一走本服务的归档路径：

- ``create_asset``：手动新建（当前仅 note 类型经 API 暴露），复刻原
  ``api/assets.py::create_asset`` 的「写行 → commit → 非草稿懒索引」顺序；
- ``upsert_asset_by_source``：按 ``(user_id, source_type, source_id)`` 幂等归档——
  同来源重复归档覆盖更新（version+1 / indexed_hash=None 触发重建），
  IntegrityError 兜底并发窗口；
- ``build_jd_asset_content`` / ``build_interview_asset_content``：把业务实体拼成
  带 Markdown 标题的归档文本（``#``/``##`` 便于 chunk_by_sections 分节），
  含 JD 评分卡 / 面试评分卡摘要（Agent 检索的高价值素材）。

索引时机：先 commit 资产行、再调 ``ensure_indexed``（其内部会 commit/rollback），
复刻 ``api/assets.py`` 既有顺序，避免事务内调用导致向量已写、行未持久化的窗口。
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_asset import KnowledgeAsset
from services.rag.clients import knowledge_collection_name
from services.rag.ensure_indexed import ensure_indexed

# 归档来源标记（source_type 取值）：业务表 → 知识资产 的溯源维度，
# 区别于 asset_type（jd/interview/note 内容分类）。每个来源最多一条资产（唯一约束）。
SOURCE_JOB_APPLICATION = "job_application"
SOURCE_INTERVIEW_SESSION = "interview_session"


def _sha256(content: str) -> str:
    """资产内容哈希（与 resumes / ensure_indexed 同款，D2 脏标记）。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def _commit_and_index(
    db: AsyncSession, user_id: int, asset: KnowledgeAsset
) -> KnowledgeAsset:
    """commit 资产行 + 懒索引 + 重读（复刻 api/assets.py 顺序）。

    ensure_indexed 失败路径会 rollback（expire 所有 ORM 对象），故 commit 后重读，
    避免 model_validate 触发 sync lazy load → MissingGreenlet，同时拿到最新 indexed 状态。
    """
    await db.commit()
    await db.refresh(asset)
    await ensure_indexed(
        db,
        user_id=user_id,
        asset_id=asset.id,
        asset_type=asset.asset_type,
        collection=knowledge_collection_name(user_id),
    )
    await db.refresh(asset)
    return asset


async def create_asset(
    db: AsyncSession,
    user_id: int,
    *,
    asset_type: str,
    title: str,
    content: str,
    is_draft: bool = False,
    source_type: str | None = None,
    source_id: int | None = None,
) -> KnowledgeAsset:
    """创建一条知识资产（草稿只进工作区不索引；非草稿懒触发 ensure_indexed）。"""
    asset = KnowledgeAsset(
        user_id=user_id,
        asset_type=asset_type,
        title=title,
        content=content,
        content_hash=_sha256(content),
        is_draft=is_draft,
        version=1,
        index_version=0,
        source_type=source_type,
        source_id=source_id,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    if not asset.is_draft:
        await ensure_indexed(
            db,
            user_id=user_id,
            asset_id=asset.id,
            asset_type=asset.asset_type,
            collection=knowledge_collection_name(user_id),
        )
        # ensure_indexed 失败路径会 rollback（expire 所有 ORM 对象），重读一次
        await db.refresh(asset)
    return asset


async def upsert_asset_by_source(
    db: AsyncSession,
    user_id: int,
    *,
    source_type: str,
    source_id: int,
    asset_type: str,
    title: str,
    content: str,
) -> KnowledgeAsset:
    """按业务来源幂等归档：已有资产 → 覆盖更新（重建索引）；否则新建。

    - 更新分支：title/content/content_hash 刷新、version+=1、indexed_hash=None
      （脏标记置空触发 ensure_indexed 重建）、is_draft 置 False；
    - 并发兜底：唯一约束 (user_id, source_type, source_id) 撞车抛 IntegrityError
      → rollback → 重查走更新分支（个人工具单用户并发概率低，重试一次足够）。
    """
    stmt = select(KnowledgeAsset).where(
        KnowledgeAsset.user_id == user_id,
        KnowledgeAsset.source_type == source_type,
        KnowledgeAsset.source_id == source_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing is None:
        try:
            return await create_asset(
                db,
                user_id,
                asset_type=asset_type,
                title=title,
                content=content,
                is_draft=False,
                source_type=source_type,
                source_id=source_id,
            )
        except IntegrityError:
            # 并发：另一请求刚插入，回滚后重查必能命中，走更新分支
            await db.rollback()
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing is None:
                raise

    # 更新分支：覆盖内容 + 脏标记 → 触发重建
    existing.title = title
    existing.content = content
    existing.content_hash = _sha256(content)
    existing.version += 1
    existing.indexed_hash = None
    existing.is_draft = False
    return await _commit_and_index(db, user_id, existing)


def build_jd_asset_content(app) -> str:
    """把投递记录拼成归档 JD 文本（含评分卡摘要）。app 为 JobApplication ORM 对象。"""
    parts = [f"# {app.company} {app.position} JD"]
    if app.jd_text:
        parts.append(app.jd_text.strip())

    sc = app.jd_scorecard or {}
    summary = []
    if sc.get("grade"):
        summary.append(f"Grade: {sc['grade']}")
    if sc.get("comp_min") is not None and sc.get("comp_max") is not None:
        summary.append(f"薪资区间: {sc['comp_min']}-{sc['comp_max']} 万/年")
    if sc.get("pain_line"):
        summary.append(f"核心痛点: {sc['pain_line']}")
    if sc.get("gaps"):
        summary.append(f"差距项: {'；'.join(sc['gaps'])}")
    if summary:
        parts.append("## JD 评分卡摘要\n" + "\n".join(summary))
    return "\n\n".join(parts)


def build_interview_asset_content(session) -> str:
    """把面试复盘记录拼成归档文本（含 JD / 问答 / 评分卡 / 备注）。"""
    parts = [f"# {session.company} {session.position} 面试复盘"]

    if session.jd_text:
        parts.append(f"## JD\n{session.jd_text.strip()}")

    questions = session.questions or []
    answers = session.answers or []
    if questions:
        qa_lines = []
        for i, q in enumerate(questions, 1):
            qa_lines.append(f"Q{i}: {q}")
            if i - 1 < len(answers) and answers[i - 1]:
                qa_lines.append(f"A{i}: {answers[i - 1]}")
        parts.append("## 问答\n" + "\n".join(qa_lines))

    if session.scorecard:
        scorecard = session.scorecard
        score_lines: list[str] = []
        overall = scorecard.get("overall_score", scorecard.get("overall"))
        if isinstance(overall, (int, float)):
            score_lines.append(f"总体评分：{overall:g}/100")

        dimensions: list[str] = []
        for item in scorecard.get("competency_scores") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("competency") or item.get("name")
            score = item.get("score")
            if isinstance(name, str) and isinstance(score, (int, float)):
                dimensions.append(f"- {name}：{score:g}/100")
        if dimensions:
            score_lines.append("维度评分：\n" + "\n".join(dimensions))

        strengths = scorecard.get("strengths") or scorecard.get("strong") or []
        if isinstance(strengths, list):
            values = [str(item).strip() for item in strengths if str(item).strip()]
            if values:
                score_lines.append("表现亮点：\n" + "\n".join(f"- {item}" for item in values))

        weaknesses = scorecard.get("weak_competencies") or scorecard.get("weak") or []
        if isinstance(weaknesses, list):
            values = [str(item).strip() for item in weaknesses if str(item).strip()]
            if values:
                score_lines.append("待改进：\n" + "\n".join(f"- {item}" for item in values))

        summary = scorecard.get("notes")
        if isinstance(summary, str) and summary.strip():
            score_lines.append("复盘总结：\n" + summary.strip())

        if score_lines:
            parts.append("## 评分卡\n" + "\n\n".join(score_lines))

    if session.notes:
        parts.append(f"## 备注\n{session.notes.strip()}")
    return "\n\n".join(parts)
