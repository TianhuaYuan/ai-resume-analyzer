"""job_applications.py — 投递状态机 API（J 功能，阶段 5）。

投递追踪 CRUD + 状态流转（STATUS_FLOW 校验，轮次可跳过，timeline 自动追加）+
JD 评分卡 + 去重检测 + 软删除垃圾箱 + 看板（截止红黄绿/停留提醒/今日队列）。
错误码统一走 AppException（core/exceptions.py），非本人记录一律 404。
"""

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.database import get_db
from core.exceptions import AppException
from models.user import User
from schemas.assets import AssetResponse
from schemas.job_application import (
    DashboardResponse,
    DuplicateItem,
    JobApplicationCreate,
    JobApplicationCreateResult,
    JobApplicationListResponse,
    JobApplicationResponse,
    JobApplicationStatusUpdate,
    JobApplicationUpdate,
)
from services import asset_service, job_application_service as svc
from services.audit_log_service import write_audit_log

router = APIRouter(prefix="/job-applications", tags=["job-applications"])


def _to_response(app) -> JobApplicationResponse:
    """ORM → response model，补派生字段（stay_days / deadline_status）。"""
    data = JobApplicationResponse.model_validate(app).model_dump()
    data["stay_days"] = svc.compute_stay_days(app)
    data["deadline_status"] = svc.deadline_status(app)
    return JobApplicationResponse.model_validate(data)


def _duplicates_to_items(dupes: list) -> list[DuplicateItem]:
    return [
        DuplicateItem(id=d.id, company=d.company, position=d.position, status=d.status)
        for d in dupes
    ]


@router.post("", response_model=JobApplicationCreateResult, status_code=status.HTTP_201_CREATED)
async def create_application(
    body: JobApplicationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建投递记录（可粘贴 JD/URL，可选生成评分卡；检测已有近似记录用于去重）。"""
    app, dupes = await svc.create_application(
        db,
        current_user.id,
        company=body.company,
        position=body.position,
        url=body.url,
        status=body.status,
        priority=body.priority,
        deadline=body.deadline,
        notes=body.notes,
        jd_text=body.jd_text,
        generate_scorecard=body.generate_scorecard,
    )
    await write_audit_log(db, user_id=current_user.id, action="job_application_create", target_type="job_application", target_id=str(app.id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID")}, ip=request.client.host if request.client else None)
    return JobApplicationCreateResult(
        application=_to_response(app),
        duplicates=_duplicates_to_items(dupes),
    )


@router.get("", response_model=JobApplicationListResponse)
async def list_applications(
    status_filter: str | None = Query(None, alias="status", description="按状态过滤"),
    priority: str | None = Query(None, description="按优先级过滤"),
    keyword: str | None = Query(None, description="按公司/岗位/备注关键词模糊匹配"),
    deleted: bool = Query(False, description="True=查看垃圾箱（软删除）记录"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页列表（默认排除软删除）。"""
    items, total = await svc.list_applications(
        db,
        current_user.id,
        status=status_filter,
        priority=priority,
        keyword=keyword,
        deleted=deleted,
        page=page,
        limit=limit,
    )
    return JobApplicationListResponse(
        items=[_to_response(i) for i in items],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit,
    )


# 注意：/dashboard 必须在 /{application_id} 之前注册，否则 "dashboard" 会被当 application_id
@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """看板数据：统计 + 截止红黄绿 + 今日队列（致谢/催办/失联）。"""
    return await svc.build_dashboard(db, current_user.id)


@router.get("/{application_id}", response_model=JobApplicationResponse)
async def get_application(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查单条详情（含 timeline / jd_scorecard）。非本人 → 404。"""
    app = await svc.get_application(db, current_user.id, application_id)
    return _to_response(app)


@router.put("/{application_id}", response_model=JobApplicationCreateResult)
async def update_application(
    application_id: int,
    body: JobApplicationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新投递记录（不含状态流转）。返回更新后的记录 + 重复检测。"""
    app, dupes = await svc.update_application(
        db,
        current_user.id,
        application_id,
        company=body.company,
        position=body.position,
        url=body.url,
        priority=body.priority,
        deadline=body.deadline,
        notes=body.notes,
        jd_text=body.jd_text,
        generate_scorecard=body.generate_scorecard,
    )
    await write_audit_log(db, user_id=current_user.id, action="job_application_update", target_type="job_application", target_id=str(app.id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID")}, ip=request.client.host if request.client else None)
    return JobApplicationCreateResult(
        application=_to_response(app),
        duplicates=_duplicates_to_items(dupes),
    )


@router.post("/{application_id}/status", response_model=JobApplicationResponse)
async def transition_status(
    application_id: int,
    body: JobApplicationStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """状态流转：校验 STATUS_FLOW 合法性（轮次可跳过），timeline 自动追加。"""
    app = await svc.transition_status(
        db,
        current_user.id,
        application_id,
        new_status=body.new_status,
        note=body.note,
    )
    await write_audit_log(db, user_id=current_user.id, action="job_application_status", target_type="job_application", target_id=str(app.id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID"), "status": body.new_status}, ip=request.client.host if request.client else None)
    return _to_response(app)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    application_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除（进垃圾箱）。"""
    await svc.soft_delete(db, current_user.id, application_id)
    await write_audit_log(db, user_id=current_user.id, action="job_application_delete", target_type="job_application", target_id=str(application_id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID")}, ip=request.client.host if request.client else None)
    return None


@router.post("/{application_id}/restore", response_model=JobApplicationResponse)
async def restore_application(
    application_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """从垃圾箱恢复。"""
    app = await svc.restore_application(db, current_user.id, application_id)
    await write_audit_log(db, user_id=current_user.id, action="job_application_restore", target_type="job_application", target_id=str(app.id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID")}, ip=request.client.host if request.client else None)
    return _to_response(app)


@router.post(
    "/{application_id}/archive",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def archive_application(
    application_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把投递的 JD 文本归档为知识资产（asset_type=jd，供 Agent 检索）。

    - 软删除（垃圾箱）投递不允许归档
    - 无 JD 内容（jd_text / jd_scorecard 均空）→ 400
    - 幂等：同来源重复归档 → 覆盖更新资产（version+1 重建索引）
    - 非本人 → 404（防枚举）

    错误码：
    - 401 未登录
    - 404 记录不存在或非本人
    - 400 已进垃圾箱 / 无 JD 内容
    """
    app = await svc.get_application(db, current_user.id, application_id)
    if app.deleted_at is not None:
        raise AppException(status_code=400, detail="投递记录已在垃圾箱，无法归档")
    if not (app.jd_text or app.jd_scorecard):
        raise AppException(status_code=400, detail="该投递没有 JD 内容，无法归档")

    asset = await asset_service.upsert_asset_by_source(
        db,
        current_user.id,
        source_type=asset_service.SOURCE_JOB_APPLICATION,
        source_id=app.id,
        asset_type="jd",
        title=f"{app.company} {app.position} JD",
        content=asset_service.build_jd_asset_content(app),
    )
    await write_audit_log(db, user_id=current_user.id, action="job_application_archive", target_type="job_application", target_id=str(application_id), detail={"result": "success", "request_id": request.headers.get("X-Request-ID")}, ip=request.client.host if request.client else None)
    return AssetResponse.model_validate(asset)
