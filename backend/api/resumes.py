import logging
import os

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from core.config import settings
from core.database import get_db
from core.security import detect_prompt_injection
from models.resume import Resume
from models.resume_module import ResumeModule
from models.user import User
from schemas.resume import (
    AnalyzeRequest,
    AnalyzeResponse,
    AtsAuditResponse,
    AnalysisStatusResponse,
    BackgroundAnalyzeResponse,
    ChunkItem,
    ChunksResponse,
    CompareRequest,
    CompareResponse,
    FullAnalyzeResponse,
    MatchJDRequest,
    MatchJDResponse,
    ResumeListResponse,
    ResumeModulesData,
    ResumeResponse,
    UploadAsyncResponse,
)
from schemas.resume_module import (
    BuilderCreateRequest,
    BuilderDraftUpdateRequest,
    BuilderResumeResponse,
    BuilderUpdateRequest,
    ResumeFamilyItem,
    ResumeModuleCreate,
    ResumeModuleResponse,
    ResumeStyle,
)
from services import analyze_service, match_jd_service, resume_service
from services import pending_changes as pending_changes_service
from services.analytics_service import record_event
from services.edit_lock import (
    acquire_edit_lock,
    get_lock_holder,
    is_edit_locked,
    release_edit_lock,
    renew_edit_lock,
)
from services.rag import chunks_service
from services.rag.clients import knowledge_collection_name
from services.rag.metadata import META_ASSET_ID, META_IS_LATEST, META_VERSION
from services.vector_store import get_vector_store
from services.resume_analysis_cache import VALID_ANALYSIS_TYPES, get_analysis_cache
from services.resume_analyze_producer import publish_analyze_task
from services.resume_parse_producer import publish_parse_task
from services.resume_builder import (
    complete_resume,
    copy_resume_as_new,
    create_builder_resume,
    get_resume_with_modules,
    update_resume_draft,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/resumes", tags=["resumes"])


async def _find_resume_by_idempotency_key(
    db: AsyncSession, user_id: int, idempotency_key: str
) -> Resume | None:
    """按 (用户, idempotency_key) 查已有简历，用于幂等去重。"""
    result = await db.execute(
        select(Resume).where(Resume.user_id == user_id, Resume.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


def _guard_jd_text(jd_text: str) -> None:
    """P1-18: jd_text 进 LLM 前的注入安检，命中注入模板即拒绝（422）。

    jd_text 会拼进 user_prompt 发给 LLM，必须和 /qa/ask 的问题一样做注入安检，
    防止 "忽略以上指令" 之类的攻击劫持模型输出。
    """
    suspicious, reason = detect_prompt_injection(jd_text)
    if suspicious:
        logger.warning("检测到疑似提示注入，已拒绝: %s", reason)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="JD 文本含疑似提示注入内容，已拒绝处理",
        )


def _upload_estimated_seconds() -> int:
    """上传简历处理预估总耗时（秒），供前端提示"预计等待时间"。"""
    return settings.ESTIMATED_PARSE_SECONDS + settings.ESTIMATED_MATERIALIZE_SECONDS


@router.post("", response_model=UploadAsyncResponse)
async def upload_resume(
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传简历（幂等）。

    带 Idempotency-Key 且当前用户已存在同 key 的简历时，直接返回已有记录（200），
    避免前端重试/网络抖动导致重复创建简历；否则新建（202）并异步解析+分块+向量化。

    A1: 解析任务通过 publish_parse_task 入队（RabbitMQ 或进程内后台），
    不再依赖 BackgroundTasks（服务重启即丢）。

    P1-9: 应用层短路检查 + DB 层 UNIQUE 约束双重防御并发竞态。
    即使两个请求同时通过短路检查，DB UNIQUE 也会让第二个 commit 抛 IntegrityError，
    回滚后查已有记录返回，并清理本次写入的孤儿文件。

    注意：user_id 必须在 rollback 前提取为局部变量。rollback 会让 session 中所有
    ORM 对象 expired，之后访问 current_user.id 会触发 sync lazy load → MissingGreenlet。
    """
    user_id = current_user.id  # 提前提取，避免 rollback 后访问 expired 属性

    # ── 幂等短路：同 key 已存在 → 返回已有记录 ──
    if idempotency_key:
        existing = await _find_resume_by_idempotency_key(db, user_id, idempotency_key)
        if existing is not None:
            response.status_code = 200
            return UploadAsyncResponse(
                id=existing.id,
                filename=existing.filename,
                status=existing.status,
                estimated_seconds=_upload_estimated_seconds(),
            )

    file_path, filename = await resume_service.save_upload_file(file)

    # P1-9: idempotency_key 与基本信息一起写入，触发 UNIQUE 约束兜底并发竞态
    try:
        resume = await resume_service.create_resume_quick(
            db, user_id, filename, file_path, idempotency_key=idempotency_key
        )
    except IntegrityError:
        # 并发竞态：另一个请求已先一步写入同 (user_id, idempotency_key) 的 resume
        await db.rollback()
        existing = await _find_resume_by_idempotency_key(db, user_id, idempotency_key)
        if existing is not None:
            # 清理本次写入的孤儿文件（避免文件系统残留）
            try:
                os.remove(file_path)
            except Exception:
                logger.warning("Failed to clean up orphan file: %s", file_path)
            response.status_code = 200
            return UploadAsyncResponse(
                id=existing.id,
                filename=existing.filename,
                status=existing.status,
                estimated_seconds=_upload_estimated_seconds(),
            )
        # 罕见：IntegrityError 但查不到记录（如其他约束冲突）
        # 转成 HTTPException 500，避免裸 IntegrityError 冒泡到 middleware 层
        # （BaseHTTPMiddleware 场景下全局 Exception handler 捕获不可靠）
        logger.exception(
            "IntegrityError with no existing resume for idempotency_key=%s", idempotency_key
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="简历上传失败，请重试",
        )

    # T37: 漏斗埋点（best-effort，失败不影响上传主流程）
    await record_event(db, user_id, "resume.upload")

    # A1: 解析任务入队（RabbitMQ 或进程内后台），不阻塞请求
    await publish_parse_task(
        resume_id=resume.id,
        user_id=user_id,
        file_path=file_path,
    )

    response.status_code = 202
    return UploadAsyncResponse(
        id=resume.id,
        filename=resume.filename,
        status=resume.status,
        estimated_seconds=_upload_estimated_seconds(),
    )


def _to_builder_response(
    resume: Resume, modules: list, modules_materialized: bool = True
) -> BuilderResumeResponse:
    """将 Resume + ResumeModule 列表转为 BuilderResumeResponse。

    模块按 sort_order 排序返回，保证 POST/PUT/GET 响应一致。
    modules_materialized: 上传简历懒物化是否成功（False=反解析失败，前端提示粘贴导入）。
    """
    sorted_modules = sorted(modules, key=lambda m: (m.sort_order, m.id))
    return BuilderResumeResponse(
        id=resume.id,
        filename=resume.filename,
        status=resume.status,
        source=resume.source,
        style=resume.style,
        version=resume.version,
        created_at=resume.created_at,
        is_indexed=resume.indexed_hash is not None,
        is_stale=bool(resume.content_hash) and resume.content_hash != resume.indexed_hash,
        modules_materialized=modules_materialized,
        language=resume.language,
        family_id=resume.family_id,
        modules=[
            ResumeModuleResponse(
                id=m.id,
                resume_id=m.resume_id,
                module_type=m.module_type,
                content=m.content,
                sort_order=m.sort_order,
                created_at=m.created_at,
                # G 可信度控制：透传 source，前端 diff 弹窗据此显示「AI 推断内容」徽标
                source=m.source,
            )
            for m in sorted_modules
        ],
    )


@router.post("/builder", response_model=BuilderResumeResponse, status_code=status.HTTP_201_CREATED)
async def create_builder_resume_endpoint(
    body: BuilderCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """新建 builder 简历（source=builder, status=draft）+ 初始模块。

    spec F 端点第 258 行：POST /api/v1/resumes/builder 建行 + resume_modules + parsed_text。
    草稿阶段 parsed_text 为空，T24 保存并完成时从模块合并生成。

    错误码：
    - 401 未登录
    - 422 模块 content 校验失败（T22 schema）
    """
    resume, modules = await create_builder_resume(db, current_user.id, body)
    # T37: 漏斗埋点（best-effort，失败不影响构建主流程）
    await record_event(db, current_user.id, "resume.builder_create")
    return _to_builder_response(resume, modules)


@router.get("", response_model=ResumeListResponse)
async def list_resumes(
    limit: int = Query(20, ge=1, le=100, description="每页数量，1-100"),
    offset: int = Query(0, ge=0, description="偏移量，>=0"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页查当前用户的简历列表。

    P1-16: limit/offset 加上限校验，防止恶意大请求拉取全量数据。
    同时 eager load resume_modules（批量查询，非 N+1），附带到每个简历的 modules_data 字段，
    前端卡片可用 ResumeTemplateView 渲染缩略预览。
    """
    items, total = await resume_service.get_user_resumes(db, current_user.id, limit, offset)

    # 批量加载 modules（1 次查询，避免 N+1）
    modules_by_resume: dict[int, list[ResumeModule]] = {}
    if items:
        resume_ids = [r.id for r in items]
        modules_result = await db.execute(
            select(ResumeModule)
            .where(ResumeModule.resume_id.in_(resume_ids))
            .order_by(ResumeModule.resume_id, ResumeModule.sort_order, ResumeModule.id)
        )
        for m in modules_result.scalars().all():
            modules_by_resume.setdefault(m.resume_id, []).append(m)

    # 组装响应（附加 modules_data）
    response_items = []
    for r in items:
        r_modules = modules_by_resume.get(r.id, [])
        style_raw = r.style
        modules_data = None
        if r_modules or style_raw:
            modules_data = ResumeModulesData(
                modules=[
                    {"id": m.id, "resume_id": m.resume_id, "module_type": m.module_type, "content": m.content, "sort_order": m.sort_order}
                    for m in r_modules
                ],
                style=style_raw,
            )
        resp = ResumeResponse.model_validate(r)
        resp.modules_data = modules_data
        response_items.append(resp)

    return ResumeListResponse(items=response_items, total=total)


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查单份简历（含处理状态）。非本人→404。"""
    return await resume_service.get_resume(db, resume_id, current_user.id)


@router.put("/{resume_id}", response_model=BuilderResumeResponse)
async def update_resume_endpoint(
    resume_id: int,
    mode: str = Query(..., description="保存模式: draft（草稿 last-write-wins）| complete（保存并完成）"),
    body: BuilderUpdateRequest = None,  # type: ignore[assignment]
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """编辑保存简历。

    spec F 端点第 259 行：请求体显式 mode: draft|complete。
    - mode=draft: last-write-wins（不查 version、不 bump version），spec A5#66。
    - mode=complete: 带版本乐观锁 → 合并 parsed_text → drop/rebuild Chroma → ready → 触发 L3。

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 version 不匹配 / 非 draft/ready 状态
    - 422 mode 不支持 / version 缺失 / 模块 content 校验失败
    - 500 向量化重建失败
    """
    if mode == "complete":
        if body is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="请求体不能为空",
            )

        resume, modules = await complete_resume(db, current_user.id, resume_id, body)

        # T15: L3 画像构建（后台，不阻塞响应）
        if background_tasks is not None:
            from services.react_agent.memory import build_l3_profile_background
            background_tasks.add_task(
                build_l3_profile_background,
                resume_id=resume.id,
                user_id=current_user.id,
            )

        return _to_builder_response(resume, modules)

    if mode != "draft":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"不支持的 mode: {mode}，仅支持 draft | complete",
        )

    if body is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请求体不能为空",
        )

    # draft 模式：忽略 version，转为 BuilderDraftUpdateRequest
    draft_body = BuilderDraftUpdateRequest(
        filename=body.filename,
        modules=body.modules,
        style=body.style,
    )
    resume, modules = await update_resume_draft(db, current_user.id, resume_id, draft_body)
    return _to_builder_response(resume, modules)


@router.post("/{resume_id}/copy", response_model=BuilderResumeResponse, status_code=status.HTTP_201_CREATED)
async def copy_resume(
    resume_id: int,
    language: str = Query("", max_length=20, description="副本语言（如 zh/en）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """复制简历为新草稿副本（多语言版本管理：复制后对副本翻译即可，不覆盖原稿）。

    借鉴 Magic-Resume createVersion 的整份快照思路，但另存为**独立新简历**：
    一份简历可同时保有中文/英文等多个语言版本。新副本 status=draft、version=1。
    副本继承源简历的 family_id（语言版本族），language 标注副本语言。
    非本人简历 → 404。
    """
    resume, modules = await copy_resume_as_new(
        db, current_user.id, resume_id, language=language
    )
    return _to_builder_response(resume, modules)


@router.get("/{resume_id}/family", response_model=list[ResumeFamilyItem])
async def get_resume_family(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回同 family 的所有语言版本（含自身），用于多语言版本管理下拉。非本人 → 404。"""
    src = await db.get(Resume, resume_id)
    if src is None or src.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="简历不存在或无权访问")

    root = src.family_id or src.id
    result = await db.execute(
        select(Resume)
        .where(
            or_(Resume.family_id == root, Resume.id == root),
            Resume.user_id == current_user.id,
        )
        .order_by(Resume.created_at.asc(), Resume.id.asc())
    )
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "language": r.language,
            "created_at": r.created_at,
            "source": r.source,
        }
        for r in result.scalars().all()
    ]


class ResumeTranslateRequest(BaseModel):
    """简历模块翻译请求。"""

    target_lang: str = Field("en", max_length=20, description="目标语言（zh/en/ja/ko/fr/de）")


@router.post("/{resume_id}/translate", response_model=BuilderResumeResponse)
async def translate_resume(
    resume_id: int,
    body: ResumeTranslateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将简历全部模块翻译为目标语言（多语言版本新建后自动翻译）。

    BuilderPage「新建英文版」等：POST /copy?language=en 创建副本后，对副本调用本端点
    自动翻译内容，用户跳转即得目标语言版本。翻译内容来源标注 inferred（AI 生成需核对），
    仅更新模块草稿，不合并 parsed_text（等「保存并完成」统一处理）。

    错误码：401 / 404 简历不存在或非本人 / 400 简历无模块 / 500 LLM 翻译或校验失败
    """
    from services.resume_builder import translate_resume_modules

    resume, modules = await translate_resume_modules(
        db, current_user.id, resume_id, body.target_lang
    )
    return _to_builder_response(resume, modules)


@router.get("/{resume_id}/builder", response_model=BuilderResumeResponse)
async def get_builder_resume(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 builder 简历 + 模块列表。

    BuilderPage 加载时调用，返回 resume 信息 + 所有模块。
    上传简历（source=upload）首次打开 builder 时，若 0 模块但有 parsed_text，
    尝试调用 LLM 解析为结构化模块并持久化。解析失败时不阻断 builder 加载。

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    """
    from services.resume_builder import materialize_modules_from_text

    # 懒物化：上传简历（source=upload）首次打开编辑器时自动从 parsed_text 解析模块，
    # 物化成功则 source → "builder"（标记已物化）；失败返回空模块 + materialized=False，
    # 前端可提示"粘贴导入"。物化不修改 parsed_text / content_hash。
    resume, modules, materialized = await materialize_modules_from_text(
        db, current_user.id, resume_id
    )
    return _to_builder_response(resume, modules, modules_materialized=materialized)


@router.delete("/{resume_id}", status_code=204)
async def delete_resume(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删简历。先删 MySQL（CASCADE 清历史）→ 清 Chroma → 删文件 → 清 Embedding 缓存。"""
    await resume_service.delete_resume(db, resume_id, current_user.id)
    return None


@router.post("/{resume_id}/retry", response_model=UploadAsyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_resume(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """P1-24：手动重试失败的简历处理。

    仅 status=failed 的简历可重试。重试时把状态改回 processing，
    并重新触发后台解析 → 分块 → 向量化流程（A1: 经 publish_parse_task 入队）。

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历状态不是 failed
    """
    resume = await resume_service.retry_resume_processing(db, resume_id, current_user.id)
    await publish_parse_task(
        resume_id=resume.id,
        user_id=current_user.id,
        file_path=resume.file_path,
    )
    return UploadAsyncResponse(
        id=resume.id,
        filename=resume.filename,
        status=resume.status,
        estimated_seconds=_upload_estimated_seconds(),
    )


@router.post("/{resume_id}/analyze", response_model=AnalyzeResponse)
async def post_analyze_resume(
    resume_id: int,
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分析简历内容（summary / skills / experience 三选一）。

    包装 analyze_service.analyze_resume。错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历未就绪（status != ready）
    - 422 非法 analysis_type（Pydantic Literal 拦截）或简历内容为空
    - 500 LLM 调用失败
    """
    result = await analyze_service.analyze_resume(
        db, current_user.id, resume_id, body.analysis_type
    )
    return AnalyzeResponse(**result)


@router.get("/{resume_id}/full-analyze", response_model=FullAnalyzeResponse)
async def get_full_analyze(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取一份简历的完整分析结果（summary/skills/experience/score 4 种一次性返回）。

    优先批量读 Redis 缓存，全部命中时零 LLM 调用；缺失的类型自动补齐。
    对比功能与本接口共享同一份缓存。

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历未就绪（status != ready）
    - 422 简历内容为空
    - 500 LLM 调用失败
    """
    result = await analyze_service.get_full_analysis(
        db, current_user.id, resume_id
    )
    return FullAnalyzeResponse(**result)


async def _verify_resume_ownership(
    db: AsyncSession, resume_id: int, user_id: int
) -> Resume:
    """校验简历归属并返回简历对象。不存在或非本人 → 404。"""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="简历不存在或无权访问")
    return resume


@router.get("/{resume_id}/analysis-status", response_model=AnalysisStatusResponse)
async def get_analysis_status(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询简历分析缓存状态。

    返回各类型分析是否已有缓存，供前端判断是否需要触发后台分析。
    """
    resume = await _verify_resume_ownership(db, resume_id, current_user.id)
    if resume.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"简历未就绪（当前状态: {resume.status}）",
        )

    cached_types: list[str] = []
    for atype in VALID_ANALYSIS_TYPES:
        cached = await get_analysis_cache(resume_id, atype)
        if cached is not None:
            cached_types.append(atype)

    return AnalysisStatusResponse(
        resume_id=resume_id,
        has_cache=len(cached_types) == len(VALID_ANALYSIS_TYPES),
        cached_types=cached_types,
    )


@router.post(
    "/{resume_id}/analyze-background",
    response_model=BackgroundAnalyzeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_analyze_background(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """触发后台静默分析。

    将分析任务加入队列（RabbitMQ 或同步 BackgroundTasks），
    分析完成后通过 WebSocket 推送通知。
    """
    resume = await _verify_resume_ownership(db, resume_id, current_user.id)
    if resume.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"简历未就绪（当前状态: {resume.status}）",
        )

    # 检查是否已有缓存（避免前端等不到通知）
    from services.resume_analysis_cache import get_full_analysis_cache
    existing_cache = await get_full_analysis_cache(resume_id)
    already_cached = existing_cache is not None

    if not already_cached:
        await publish_analyze_task(
            resume_id=resume_id,
            user_id=current_user.id,
            filename=resume.filename.split("/")[-1].split("\\")[-1],
        )

    return BackgroundAnalyzeResponse(
        status="accepted",
        resume_id=resume_id,
        message="分析任务已加入队列" if not already_cached else "缓存已存在",
    )


@router.get("/{resume_id}/chunks", response_model=ChunksResponse)
async def get_resume_chunks(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查简历的所有分块（chunks）。

    归属校验走 MySQL，chunk 数据走 ChromaDB。
    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历未就绪（status != ready）或 Chroma collection 不存在
    """
    # 归属校验（不存在或非本人 → 404）
    resume = await resume_service.get_resume(db, resume_id, current_user.id)

    # 状态校验（未就绪 → 409）
    if resume.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"简历未就绪（当前状态: {resume.status}）",
        )

    # 读 ChromaDB（collection 不存在 → 409）
    chunks_data = await chunks_service.get_chunks_by_resume(current_user.id, resume_id)

    return ChunksResponse(
        resume_id=resume_id,
        total=len(chunks_data),
        chunks=[ChunkItem(**c) for c in chunks_data],
    )


class ResumeVersionInfo(BaseModel):
    """单个索引版本的概要信息（T18 版本浏览）。"""

    version: int
    is_latest: bool
    chunk_count: int
    sections: list[str]


class ResumeVersionsResponse(BaseModel):
    """简历索引版本列表（T18 版本浏览）。

    versions 按版本号降序（最新在前），current_version 取简历的 index_version。
    """

    versions: list[ResumeVersionInfo]
    current_version: int


@router.get("/{resume_id}/versions", response_model=ResumeVersionsResponse)
async def get_resume_versions(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查简历的索引版本历史（T18 版本浏览）。

    读取每用户知识集合（knowledge_{user_id}）中该简历（asset_id）的所有版本
    chunks（含已退役旧版本，is_latest=False），按 metadata 的 version 分组返回：
    版本号 / 是否最新 / chunk 数 / 节段列表。

    归属校验复用 _verify_resume_ownership（不存在或非本人 → 404）。
    从未索引（collection 不存在或无 chunks）→ versions 为空列表，
    current_version 取 resume.index_version（默认 0）。

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    """
    # 归属校验（不存在或非本人 → 404），同时拿到 index_version 作 current_version
    resume = await _verify_resume_ownership(db, resume_id, current_user.id)

    collection = knowledge_collection_name(current_user.id)
    items = await get_vector_store().get(
        collection,
        where={META_ASSET_ID: resume_id},
    )

    grouped: dict[int, dict] = {}
    for item in items or []:
        meta = item.get("metadata") or {}
        try:
            version = int(meta.get(META_VERSION, 0))
        except (TypeError, ValueError):
            version = 0
        group = grouped.setdefault(
            version,
            {"version": version, "is_latest": False, "chunk_count": 0, "sections": []},
        )
        group["chunk_count"] += 1
        section = str(meta.get("section", "")).strip()
        if section and section not in group["sections"]:
            group["sections"].append(section)
        if meta.get(META_IS_LATEST):
            group["is_latest"] = True

    versions = [grouped[k] for k in sorted(grouped, reverse=True)]
    return ResumeVersionsResponse(
        versions=versions,
        current_version=resume.index_version or 0,
    )


@router.post("/{resume_id}/match-jd", response_model=MatchJDResponse)
async def post_match_jd(
    resume_id: int,
    body: MatchJDRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将简历与 JD 文本进行匹配分析。

    返回 LLM 生成的匹配分数、匹配点、差距分析和改进建议。
    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历未就绪（status != ready）
    - 422 JD 文本为空、超长或含疑似提示注入
    - 500 LLM 调用失败
    """
    # P1-18: jd_text 进 LLM 前做注入安检（和 /qa/ask 的问题一样）
    _guard_jd_text(body.jd_text)
    result = await match_jd_service.match_jd(
        db, current_user.id, resume_id, body.jd_text
    )
    return MatchJDResponse(**result)


@router.get("/{resume_id}/export")
async def export_resume(
    resume_id: int,
    format: str = Query("markdown", description="导出格式: markdown | pdf"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出简历为 PDF 或 Markdown。

    T26: 从 resume_modules 渲染导出，含零模块守卫。
    - format=markdown: 从模块拼接 Markdown 文本
    - format=pdf: render_resume HTML → WeasyPrint PDF

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 422 零模块 / 不支持的格式
    - 503 PDF 服务不可用（WeasyPrint/GTK 未安装）
    """
    from services.resume_export import export_resume_markdown, export_resume_pdf

    if format == "pdf":
        pdf_bytes, filename = await export_resume_pdf(db, current_user.id, resume_id)
        # T37: 漏斗埋点（best-effort，失败不影响导出主流程）
        await record_event(
            db, current_user.id, "resume.export", metadata={"format": "pdf"}
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if format == "markdown":
        markdown_str, filename = await export_resume_markdown(db, current_user.id, resume_id)
        # T37: 漏斗埋点（best-effort，失败不影响导出主流程）
        await record_event(
            db, current_user.id, "resume.export", metadata={"format": "markdown"}
        )
        return PlainTextResponse(
            content=markdown_str,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"不支持的导出格式: {format}，仅支持 markdown | pdf",
    )


@router.post("/{resume_id}/avatar")
async def upload_avatar(
    resume_id: int,
    file: UploadFile = File(..., description="头像图片（JPEG/PNG/WebP，最大 5MB）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """上传简历头像。

    T26: 照片安全 — MIME 白名单 / 5MB 限制 / PIL 校验 / UUID 文件名。
    上传后更新 basic_info 模块的 avatar 字段。

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 422 MIME 不支持 / 不是有效图片
    - 413 文件过大
    """
    from services.avatar_service import save_avatar
    from services.resume_builder import get_resume_with_modules

    # 校验归属
    resume, modules = await get_resume_with_modules(db, current_user.id, resume_id)

    # 获取旧头像URL（用于删除旧文件）
    old_avatar_url = None
    for mod in modules:
        if mod.module_type == "basic_info":
            content = mod.content or {}
            old_avatar_url = content.get("avatar")
            break

    # 保存头像（会自动删除旧头像文件）
    avatar_url = await save_avatar(file, resume_id, old_avatar_url)

    # 更新 basic_info 模块的 avatar 字段
    basic_info_module = None
    for mod in modules:
        if mod.module_type == "basic_info":
            basic_info_module = mod
            break

    if basic_info_module:
        content = basic_info_module.content or {}
        content["avatar"] = avatar_url
        basic_info_module.content = content
    else:
        # 如果没有 basic_info 模块，创建一个只含 avatar 的
        new_module = ResumeModule(
            resume_id=resume_id,
            module_type="basic_info",
            content={"name": "未命名", "avatar": avatar_url},
            sort_order=0,
        )
        db.add(new_module)

    await db.commit()

    logger.info("Avatar uploaded: resume=%d, url=%s", resume_id, avatar_url)
    return {"avatar_url": avatar_url}


@router.get("/{resume_id}/preview")
async def get_preview(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取简历预览 HTML。

    T27: content hash 缓存（TTL 5min）。
    BuilderPage iframe 实时预览调用此端点。
    零模块时返回空模板（不报 422）。

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    """
    from services.resume_preview import get_resume_preview

    html, cache_hit = await get_resume_preview(db, current_user.id, resume_id)
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "X-Cache-Hit": "true" if cache_hit else "false",
            "Cache-Control": "private, max-age=300",
        },
    )


@router.post("/{resume_id}/preview")
async def preview_with_data(
    resume_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """用前端传入的 modules + style 实时渲染预览 HTML（不读数据库）。

    BuilderPage 编辑时样式/内容变更 → 立即 POST 当前数据 → 返回渲染 HTML。
    避免等待 5s 自动保存后 GET /preview 才能拿到最新样式的问题。

    请求体：{modules: [{module_type, content, sort_order}], style: {...}}
    """
    from services.resume_builder import get_resume_with_modules
    from services.resume_template import render_resume

    # 校验归属（只需确认简历存在且属于当前用户）
    resume, _ = await get_resume_with_modules(db, current_user.id, resume_id)

    # 解析传入的 modules
    raw_modules = body.get("modules", [])
    modules = [
        ResumeModuleCreate(
            module_type=m["module_type"],
            content=m.get("content", {}),
            sort_order=m.get("sort_order", idx),
        )
        for idx, m in enumerate(raw_modules)
    ]

    # 解析 style
    raw_style = body.get("style")
    style = ResumeStyle(**raw_style) if raw_style else ResumeStyle()

    # 渲染
    html = render_resume(modules, style, resume.filename)
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.post("/parse-to-modules")
async def parse_to_modules(
    body: dict,
    current_user: User = Depends(get_current_user),
):
    """将简历纯文本反解析为结构化模块列表。

    T27: LLM 解析 → pydantic 校验 → 格式错误回灌重试 1 次。
    用于上传简历后自动填充 builder 模块。

    请求体：
    - text: 简历纯文本（必填，长度 10-50000）

    错误码：
    - 401 未登录
    - 422 文本为空 / 过短 / 过长
    - 500 LLM 调用失败 / 校验失败
    """
    from services.resume_parser import parse_text_to_modules

    text = body.get("text", "") if isinstance(body, dict) else ""
    if not text or len(text.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="简历文本不能为空且至少 10 个字符",
        )
    if len(text) > 50000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="简历文本过长（超过 50000 字符）",
        )

    try:
        modules = await parse_text_to_modules(text, user_id=current_user.id)
    except ValueError as e:
        logger.warning("parse_to_modules failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception("parse_to_modules unexpected error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="简历反解析失败，请稍后重试",
        ) from e

    return {
        "modules": [
            {
                "module_type": m.module_type.value,
                "content": m.content,
                "sort_order": m.sort_order,
            }
            for m in modules
        ],
        "total": len(modules),
    }


# ═══════════════════════════════════════════════════════════
# 内联 AI 端点（UP 简历对齐：一键优化 / 智能检查 / 智能改写）
# ═══════════════════════════════════════════════════════════

# 字段隔离约束：条目级 AI 只操作传入的单一字段文本，
# 不得把同模块其它字段（姓名/联系方式/日期等）改写进去，也不得虚构字段外信息。
# optimize / rewrite 两处 system_prompt 复用，避免文案漂移。
_AI_FIELD_ISOLATION_PROMPT = (
    "3. 只对用户提供的这段文本进行操作，文本之外的任何信息（姓名、电话、邮箱、"
    "公司、学校、日期等其他字段内容）一律不得修改、增删或虚构；不得新增原文没有的数据\n"
    "4. 若指令涉及文本中没有的信息，以文本为准，不自行补全\n"
)

# E4 事实天花板约束（fieldwork 职业档案天花板对照）：以已保存模块为唯一事实源，
# AI 建议只改写不新增事实——不得引入档案外成就/经历/技能，不得编造量化数字。
_AI_CEILING_CONSTRAINT = (
    "5. 【事实天花板】以提供的「已保存模块事实源」为唯一事实依据：只能改写措辞、"
    "结构与表述，不得引入事实源中不存在的新经历、新成就、新公司/学校/项目/技能；\n"
    "6. 若指令要求增加量化数据，只能在原文已有成就的基础上优化表述，绝不虚构指标数字；"
    "不得把推断内容写成既定事实。\n"
)


async def _load_module_fact_source(
    resume_id: int,
    module_type: str,
    db: AsyncSession,
    user_id: int,
) -> str | None:
    """读取已保存模块 content 作为事实源（best-effort，失败返回 None）。

    E4：条目级 AI 以已保存模块为唯一事实依据；脱敏后传给 LLM。
    """
    try:
        import json as _json

        from services.resume_builder import get_resume_with_modules
        from utils.privacy import sanitize_for_ai

        _, modules = await get_resume_with_modules(db, user_id, resume_id)
        for m in modules:
            if m.module_type == module_type:
                content = sanitize_for_ai(m.content) if isinstance(m.content, dict) else m.content
                # 1200 字符截断：事实源仅供约束不新增事实，过长反而拖慢 prefill
                return _json.dumps(content, ensure_ascii=False)[:1200]
    except HTTPException:
        return None
    except Exception:
        return None
    return None


class AIOptimizeRequest(BaseModel):
    """一键优化请求。"""
    text: str
    module_type: str = "basic_info"


class AICheckRequest(BaseModel):
    """智能检查请求。"""
    text: str
    module_type: str = "basic_info"
    check_field: str | None = None  # 可选：聚焦检查某字段（如 description/summary）


class AIRewriteRequest(BaseModel):
    """智能改写请求。"""
    text: str
    instruction: str = ""
    module_type: str = "basic_info"


class RoleScoreRequest(BaseModel):
    """多角色评分请求（E3）。"""

    target_position: str | None = Field(None, max_length=100, description="目标岗位（可选）")


class AICheckIssue(BaseModel):
    """智能检查发现的问题。"""
    severity: str  # high / medium / low
    category: str  # 量化问题 / 描述模糊 / 角色不清 等
    description: str
    field: str | None = None  # 可选：问题所属字段标签（如「工作描述」，LLM 标注）


class AICheckResponse(BaseModel):
    """智能检查结果。"""
    issues: list[AICheckIssue]


@router.post("/{resume_id}/ai/optimize")
async def ai_optimize(
    resume_id: int,
    body: AIOptimizeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一键优化模块文本。

    调用 LLM 对文本进行专业润色优化，返回优化后的文本。
    - 强化动词（如"专注于"→"深耕"）
    - 增加量化描述建议
    - 优化结构清晰度

    错误码：401 / 404 / 422 文本为空 / 500 LLM 调用失败
    """
    if not body.text or len(body.text.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文本内容过短，无法优化",
        )

    system_prompt = (
        "你是一位资深简历优化专家。请对用户提供的简历文本进行一键优化，"
        "使其更专业、更有吸引力。要求：\n"
        "1. 使用更强的动词（如'深耕'代替'专注于'，'主导'代替'参与'）\n"
        "2. 结构更清晰，适当使用分段或要点\n"
        + _AI_FIELD_ISOLATION_PROMPT
        + _AI_CEILING_CONSTRAINT
        + "7. 语言更精炼，去除冗余表述\n"
        "8. 直接输出优化后的文本，不要加任何解释或前缀\n"
    )

    # E4：以已保存模块为唯一事实源（只改写不新增事实）
    fact_source = await _load_module_fact_source(
        resume_id, body.module_type, db, current_user.id
    )

    try:
        from services.rag.pipeline import llm_generate

        result = await llm_generate(
            system=system_prompt,
            user=(
                f"模块类型：{body.module_type}\n\n"
                f"已保存模块事实源（唯一事实依据，不得引入其外新事实）：\n"
                f"{fact_source or '（该模块暂无已保存内容）'}\n\n"
                f"请优化以下文本：\n\n{body.text}"
            ),
            temperature=0.3,
            max_tokens=800,  # 条目级文本较短，限制输出防模型超长生成拖慢响应
            user_id=current_user.id,
        )
        return {"optimized_text": result, "original_text": body.text}
    except Exception as e:
        # P0-5：不把原始异常回显给客户端（可能泄露 API key 片段/内部错误栈），
        # 完整 traceback 留在服务端日志（logger.exception）。
        logger.exception("AI optimize failed: resume=%d", resume_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI 优化失败，请稍后重试。",
        ) from e


@router.post("/{resume_id}/ai/check")
async def ai_check(
    resume_id: int,
    body: AICheckRequest,
    current_user: User = Depends(get_current_user),
):
    """智能检查模块文本。

    分析文本中的常见简历问题，返回分类问题列表。
    检查维度：
    - 量化问题：缺少数据支撑
    - 描述模糊：技术栈罗列未说明解决的问题
    - 角色不清：个人贡献与团队协作边界模糊

    错误码：401 / 404 / 422 文本为空 / 500 LLM 调用失败
    """
    if not body.text or len(body.text.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文本内容过短，无法检查",
        )

    system_prompt = (
        "你是一位资深简历审查专家。请分析用户提供的简历文本，找出其中的问题。\n"
        "检查维度：\n"
        "1. 量化问题：关键成就缺少数据支撑（如性能指标、业务价值、效率提升比例）\n"
        "2. 描述模糊：技术栈罗列但未说明解决的核心问题或独特架构方案\n"
        "3. 角色不清：个人贡献与团队协作边界模糊，动词强度不一致\n\n"
        "请以 JSON 格式返回结果，格式如下：\n"
        '{"issues": [{"severity": "high|medium|low", "category": "问题分类", "description": "具体问题描述", "field": "所属字段"}]}\n\n'
        "severity 取值：high（红色，严重影响）、medium（黄色，建议改进）、low（绿色，小问题）\n"
        "category 使用简洁中文标签，如'量化问题'、'描述模糊'、'角色不清'\n"
        "每个 issue 的 field 标注问题所属的字段标签（从原文中识别，如'工作描述'、'项目描述'、"
        "'个人简介'、'主要成就'；无法确定则省略该字段）\n"
        "只返回 JSON，不要加任何其他文字。\n"
    )

    try:
        from services.rag.pipeline import llm_generate
        import json

        user_context = f"模块类型：{body.module_type}"
        if body.check_field:
            user_context += f"，当前检查字段：{body.check_field}"
        raw = await llm_generate(
            system=system_prompt,
            user=f"{user_context}\n\n请检查以下文本：\n\n{body.text}",
            temperature=0.2,
            max_tokens=500,  # 检查只输出 JSON issues，限制输出防超长生成
            user_id=current_user.id,
        )

        # 尝试解析 JSON
        try:
            data = json.loads(raw)
            issues = data.get("issues", [])
        except (json.JSONDecodeError, ValueError):
            # 如果 LLM 没返回合法 JSON，包装为单个 issue
            issues = [
                {
                    "severity": "medium",
                    "category": "分析结果",
                    "description": raw[:500] if raw else "无法生成检查结果",
                }
            ]

        return {"issues": issues}
    except Exception as e:
        logger.exception("AI check failed: resume=%d", resume_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI 检查失败，请稍后重试。",
        ) from e


@router.post("/{resume_id}/ai/rewrite")
async def ai_rewrite(
    resume_id: int,
    body: AIRewriteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """智能改写模块文本。

    根据用户提供的指令对文本进行定制化改写。
    常见指令：更简洁专业 / 突出技术能力 / 增加量化数据 / 针对XX职位优化

    错误码：401 / 404 / 422 文本为空 / 500 LLM 调用失败
    """
    if not body.text or len(body.text.strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文本内容过短，无法改写",
        )

    instruction = body.instruction.strip() if body.instruction else "更简洁专业"

    system_prompt = (
        "你是一位资深简历改写专家。请根据用户的改写指令，对简历文本进行定制化改写。\n"
        "要求：\n"
        "1. 严格遵循用户的改写指令\n"
        "2. 保留原文的核心事实和技术栈，不编造数据\n"
        + _AI_FIELD_ISOLATION_PROMPT
        + _AI_CEILING_CONSTRAINT
        + "7. 直接输出改写后的文本，不要加任何解释或前缀\n"
    )

    # E4：以已保存模块为唯一事实源（只改写不新增事实）
    fact_source = await _load_module_fact_source(
        resume_id, body.module_type, db, current_user.id
    )

    try:
        from services.rag.pipeline import llm_generate

        result = await llm_generate(
            system=system_prompt,
            user=(
                f"模块类型：{body.module_type}\n"
                f"改写指令：{instruction}\n\n"
                f"已保存模块事实源（唯一事实依据，不得引入其外新事实）：\n"
                f"{fact_source or '（该模块暂无已保存内容）'}\n\n"
                f"请改写以下文本：\n\n{body.text}"
            ),
            temperature=0.4,
            max_tokens=800,  # 条目级文本较短，限制输出防模型超长生成拖慢响应
            user_id=current_user.id,
        )
        return {"rewritten_text": result, "original_text": body.text}
    except Exception as e:
        logger.exception("AI rewrite failed: resume=%d", resume_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI 改写失败，请稍后重试。",
        ) from e


@router.post("/{resume_id}/role-score")
async def post_role_score(
    resume_id: int,
    body: RoleScoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """多角色 LLM 评分（E3）：peer/lead/HRBP 各打 0-100 + 加权聚合。

    聚合权重来自 rubric.json（I2 可编辑，热重载）。含证据锚定。
    """
    result = await analyze_service.analyze_resume_roles(
        db, current_user.id, resume_id, body.target_position
    )
    return result


@router.post("/compare", response_model=CompareResponse)
async def compare_resumes(
    body: CompareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """多简历对比分析。

    对比 2-5 份简历的技能和项目维度。
    错误码：
    - 401 未登录
    - 404 任一简历不存在或非本人
    - 422 resume_ids 或 dimensions 不符合规范
    """
    result = await resume_service.compare_resumes(
        db, current_user.id, body.resume_ids, body.dimensions
    )
    return CompareResponse(**result)


@router.post("/{resume_id}/ats-audit", response_model=AtsAuditResponse)
async def ats_audit(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ATS 可读性模拟审计（P0-A）。

    模拟 ATS 解析简历，检出乱码段/空白段/特殊符号/图片文字/表格等问题，
    返回结构化问题清单 + 得分。纯本地规则引擎，零 LLM。

    双路径：
    - HTML 直读（始终执行，零 GTK 依赖）
    - PDF 回读（WeasyPrint 可用时追加，最接近真实 ATS）

    WeasyPrint 缺失时不抛 503，降级为 HTML 路径 + warnings。

    错误码：
    - 401 未登录
    - 404 简历不存在或非本人
    - 409 简历未就绪（status != ready/draft）
    - 422 零模块
    """
    from services.ats_audit_service import audit_resume

    result = await audit_resume(db, current_user.id, resume_id)
    return result


# ═══════════════════════════════════════════════════════════════
# 编辑锁 API（T28 edit_lock 服务层 → HTTP 端点）
# ═══════════════════════════════════════════════════════════════


class EditLockResponse(BaseModel):
    """编辑锁响应。"""
    locked: bool
    lock_token: str | None = None
    holder_id: int | None = None


class EditLockHeartbeatRequest(BaseModel):
    """心跳续期请求。"""
    lock_token: str


@router.post("/{resume_id}/lock", response_model=EditLockResponse)
async def acquire_lock(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取简历编辑锁。

    - 成功 → 200 + lock_token（前端需保存，用于续期/释放）
    - 已被他人持有 → 409 + holder_id
    """
    await resume_service.get_resume(db, resume_id, current_user.id)

    token = await acquire_edit_lock(resume_id, current_user.id)
    if token is None:
        holder = await get_lock_holder(resume_id)
        raise HTTPException(
            status_code=409,
            detail={
                "locked": True,
                "holder_id": holder,
                "message": "该简历正在被其他用户编辑",
            },
        )

    return EditLockResponse(locked=True, lock_token=token, holder_id=current_user.id)


@router.post("/{resume_id}/lock/heartbeat", response_model=EditLockResponse)
async def renew_lock(
    resume_id: int,
    body: EditLockHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """心跳续期编辑锁。

    前端每 60s 调用一次，延长锁 TTL。
    - 成功 → 200
    - 锁不存在/token 不匹配 → 409
    """
    success = await renew_edit_lock(resume_id, current_user.id, body.lock_token)
    if not success:
        raise HTTPException(
            status_code=409,
            detail={"locked": False, "message": "编辑锁已过期或无效，请重新获取"},
        )

    return EditLockResponse(locked=True, lock_token=body.lock_token, holder_id=current_user.id)


@router.delete("/{resume_id}/lock", status_code=200)
async def release_lock(
    resume_id: int,
    lock_token: str = Query(..., description="获取锁时返回的 token"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """释放编辑锁。

    - 成功 → 200
    - token 不匹配 → 409
    """
    success = await release_edit_lock(resume_id, current_user.id, lock_token)
    if not success:
        raise HTTPException(
            status_code=409,
            detail={"message": "锁 token 不匹配或锁已过期"},
        )

    return {"released": True}


# ═══════════════════════════════════════════════════════════
# E2: 改写审阅队列（PendingChange）
# ═══════════════════════════════════════════════════════════


@router.get(
    "/{resume_id}/pending-changes",
    response_model=pending_changes_service.PendingChangeListResponse,
)
async def list_pending_changes(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出简历的待审阅改动（user_id 隔离，含已接受/已拒绝历史）。"""
    items = await pending_changes_service.list_pending_changes(
        db, current_user.id, resume_id
    )
    return {"items": items, "total": len(items)}


@router.post(
    "/{resume_id}/pending-changes/{change_id}/accept",
    response_model=pending_changes_service.PendingChangeOut,
)
async def accept_pending_change(
    resume_id: int,
    change_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认保留该改动（status → accepted）。"""
    change = await pending_changes_service.accept_pending_change(
        db, current_user.id, change_id
    )
    return change


@router.post(
    "/{resume_id}/pending-changes/{change_id}/reject",
    response_model=pending_changes_service.PendingChangeOut,
)
async def reject_pending_change(
    resume_id: int,
    change_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """丢弃该改动：字段按 before 还原到模块 content，status → rejected。"""
    change = await pending_changes_service.reject_pending_change(
        db, current_user.id, change_id
    )
    return change


@router.delete("/{resume_id}/pending-changes")
async def clear_pending_changes(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清空简历的全部待审阅改动。"""
    count = await pending_changes_service.clear_pending_changes(
        db, current_user.id, resume_id
    )
    return {"cleared": count}
