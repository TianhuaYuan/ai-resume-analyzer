"""interview.py — 面试复盘闭环 API（G 功能）。

面后记录 → 录入评分卡（status: recorded → reviewed）→ 派生薄弱点 →
复盘汇总（高频薄弱点 / 训练推荐 / 历史趋势）。
设计思路对照 DeepInterview sessions + run_coach_plan，翻译为现有
FastAPI + SQLAlchemy 风格。错误码统一走 AppException（core/exceptions.py），
非本人记录一律 404（防枚举）。
"""

import logging

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from models.user import User
from schemas.assets import AssetResponse
from schemas.interview import (
    InterviewCreate,
    InterviewListResponse,
    InterviewListItem,
    InterviewResponse,
    InterviewUpdate,
    ReviewSummaryResponse,
    ScorecardUpdateResponse,
)
from services import asset_service, interview_service
from services.audit_log_service import write_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.post("", response_model=InterviewResponse, status_code=status.HTTP_201_CREATED)
async def create_interview(
    body: InterviewCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录一次面试（面后信息 + 可选评分卡一次写入）。

    body 含 scorecard 时视为已复盘（status=reviewed），否则 status=recorded。

    错误码：
    - 401 未登录
    - 422 company/position 为空或超长
    """
    session = await interview_service.create_interview(
        db,
        current_user.id,
        company=body.company,
        position=body.position,
        resume_id=body.resume_id,
        job_application_id=body.job_application_id,
        jd_text=body.jd_text,
        questions=body.questions,
        answers=body.answers,
        notes=body.notes,
        scorecard=body.scorecard,
    )
    await write_audit_log(db, user_id=current_user.id, action="interview_create", target_type="interview", target_id=str(session.id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID"), "reviewed": bool(body.scorecard)}, ip=request.client.host if request.client else None)
    return InterviewResponse.model_validate(session)


@router.get("", response_model=InterviewListResponse)
async def list_interviews(
    page: int = Query(1, ge=1, description="页码，>=1"),
    limit: int = Query(20, ge=1, le=100, description="每页数量，1-100"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页列表（按 created_at 倒序）。不含 answers/scorecard 大字段。

    错误码：
    - 401 未登录
    """
    items, total = await interview_service.get_interviews(db, current_user.id, page, limit)
    total_pages = (total + limit - 1) // limit
    return InterviewListResponse(
        items=[InterviewListItem.model_validate(i) for i in items],
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


# 注意：/review/summary 必须在 /{interview_id} 之前注册，
# 否则 "review" 会被当作 interview_id 匹配（int 转换失败 → 422）
@router.get("/review/summary", response_model=ReviewSummaryResponse)
async def review_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """复盘汇总：高频薄弱点 + 训练推荐（最弱优先）+ 历史面试趋势。

    错误码：
    - 401 未登录
    """
    return await interview_service.build_review_summary(db, current_user.id)


@router.get("/{interview_id}", response_model=InterviewResponse)
async def get_interview(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查单条面试详情（含 answers/scorecard）。非本人 → 404。

    错误码：
    - 401 未登录
    - 404 记录不存在或非本人
    """
    session = await interview_service.get_interview(db, current_user.id, interview_id)
    return InterviewResponse.model_validate(session)


@router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview(
    interview_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删面试记录。非本人 → 404。

    错误码：
    - 401 未登录
    - 404 记录不存在或非本人
    """
    await interview_service.delete_interview(db, current_user.id, interview_id)
    await write_audit_log(db, user_id=current_user.id, action="interview_delete", target_type="interview", target_id=str(interview_id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID")}, ip=request.client.host if request.client else None)
    return None


@router.put("/{interview_id}/scorecard", response_model=ScorecardUpdateResponse)
async def update_scorecard(
    interview_id: int,
    body: InterviewUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """录入/更新评分卡：scorecard 整块写入 + status=reviewed，返回派生薄弱点。

    错误码：
    - 401 未登录
    - 404 记录不存在或非本人
    - 422 scorecard 缺失
    """
    session = await interview_service.update_scorecard(
        db, current_user.id, interview_id, body.scorecard, notes=body.notes
    )
    await write_audit_log(db, user_id=current_user.id, action="interview_scorecard", target_type="interview", target_id=str(session.id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID")}, ip=request.client.host if request.client else None)
    weak = interview_service.derive_weak_competencies(session.scorecard)
    return ScorecardUpdateResponse(
        interview_id=session.id,
        status=session.status,
        weak_competencies=weak,
        scorecard=session.scorecard,
        notes=session.notes,
    )


@router.post(
    "/{interview_id}/archive",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def archive_interview(
    interview_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把一次面试复盘归档为知识资产（asset_type=interview，供 Agent 检索）。

    - 幂等：同来源（interview_session）重复归档 → 覆盖更新资产（version+1 重建索引）
    - 归档后同步触发索引，Agent search_assets 即可命中
    - 非本人 → 404（防枚举）

    错误码：
    - 401 未登录
    - 404 记录不存在或非本人
    """
    session = await interview_service.get_interview(db, current_user.id, interview_id)
    asset = await asset_service.upsert_asset_by_source(
        db,
        current_user.id,
        source_type=asset_service.SOURCE_INTERVIEW_SESSION,
        source_id=session.id,
        asset_type="interview",
        title=f"{session.company} {session.position} 面试记录",
        content=asset_service.build_interview_asset_content(session),
    )
    await write_audit_log(db, user_id=current_user.id, action="interview_archive", target_type="interview", target_id=str(interview_id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID")}, ip=request.client.host if request.client else None)
    return AssetResponse.model_validate(asset)
