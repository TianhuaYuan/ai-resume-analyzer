"""+T24: resume_builder 新建 / 草稿 / 保存并完成。

职责：
- POST /resumes/builder → 创建 source=builder, status=draft 简历 + 初始模块
- PUT /resumes/{id}?mode=draft → 草稿全量更新（不查 version、不 bump version）
- PUT /resumes/{id}?mode=complete → 保存并完成（乐观锁 → 合并 parsed_text → drop/rebuild Chroma → ready）
- GET 简历 + 模块列表

设计依据：
- spec A5#66: 草稿自动保存用 last-write-wins（不查 version、不 bump——5s 草稿被覆盖可接受）
- spec B#19: 草稿服务端 status=draft，保存并完成 → 生成 parsed_text + 向量化 → ready
- spec F 端点: 请求体显式 mode: draft|complete——draft 不带 version（last-write-wins），complete 必带 version（乐观锁）
- T22 schema: validate_module_content 四方契约入口校验 content
- T15: ready 转换时触发 L3 画像构建（双路径共享点：上传 / builder）
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from core import cache as embedding_cache
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.resume import Resume
from models.resume_module import ResumeModule
from schemas.resume_module import (
    BuilderCreateRequest,
    BuilderDraftUpdateRequest,
    BuilderUpdateRequest,
    ModuleType,
    ResumeModuleCreate,
    validate_module_content,
)
from services.rag.asset_source import ASSET_TYPE_RESUME
from services.rag.clients import knowledge_collection_name
from services.rag.ensure_indexed import ensure_indexed
from services.resume_service import set_resume_status

logger = logging.getLogger(__name__)


def _validate_modules(modules: list[ResumeModuleCreate], strict: bool = True) -> None:
    """批量校验模块 content，将 pydantic.ValidationError 转为 HTTPException(422)。

    strict=True: 完整 schema 校验（创建 / 保存并完成，要求内容完整）。
    strict=False: 草稿宽松校验，仅要求 content 为对象——编辑中间态（条目必填字段
    未填、清空姓名尚未重填等）触发 5s 自动保存时，字段完整性由保存并完成时严格把关。

    service 层调 validate_module_content 时，ValidationError 不会被 FastAPI 自动处理
    （只在请求体解析阶段才自动转 422），因此在此处显式捕获转换。
    """
    for mod in modules:
        if not strict:
            # 草稿宽松：任意 dict content 均可保存（字段完整性交给 complete 严格校验）
            if not isinstance(mod.content, dict):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"模块 {mod.module_type.value} content 必须是对象",
                )
            continue
        try:
            validate_module_content(mod.module_type, mod.content)
        except ValidationError as e:
            # 友好化：逐条提取「字段路径: 原因」，避免把原始 JSON errors 抛给前端
            errs = []
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", []) if x != "__root__")
                msg = err.get("msg", "")
                errs.append(f"{loc}: {msg}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"模块 {mod.module_type.value} 校验失败: "
                    f"{'; '.join(errs[:5]) or '字段缺失或格式错误'}"
                ),
            ) from e
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e


# 条目类模块（content.entries: [...]，含必填字段）
_ENTRY_MODULE_TYPES = frozenset(
    {
        ModuleType.EDUCATION,
        ModuleType.WORK_EXPERIENCE,
        ModuleType.PROJECT_EXPERIENCE,
        ModuleType.LANGUAGE,
        ModuleType.HONORS,
        ModuleType.CERTIFICATES,
        ModuleType.CLUB_ACTIVITIES,
        ModuleType.PUBLICATIONS,
        ModuleType.RECOMMENDATION,
    }
)


def _entry_is_blank(entry: dict) -> bool:
    """判断条目是否全空（草稿中间态残留，如刚点"添加条目"还没填）。"""
    return all(
        v is None or v == "" or (isinstance(v, list) and len(v) == 0) for v in entry.values()
    )


def _sanitize_draft_modules(modules: list[ResumeModuleCreate]) -> None:
    """草稿保存宽容化：清理编辑中间态的空值，避免必填校验 422。

    前端 5s 自动保存会在用户编辑中间态触发（刚点"添加条目"、清空姓名尚未重填、
    添加技能分类尚未命名），此时必填字段为空，严格校验会 422 导致草稿保存失败。
    草稿本就是中间态，应容忍不完整输入：
    - basic_info: name 空 → 补占位"未命名"
    - 条目类模块: 移除全空条目（未填任何内容的残留空条目）
    - skills: 移除空分类（name 空且 items 空）
    - other/custom: content 空 → 补占位"未填写"
    保存并完成时仍走严格校验（_validate_modules），要求最终内容完整。
    """
    for mod in modules:
        content = mod.content
        if mod.module_type == ModuleType.BASIC_INFO:
            if not (content.get("name") or "").strip():
                content["name"] = "未命名"
        elif mod.module_type == ModuleType.SKILLS:
            items = content.get("items")
            if isinstance(items, list):
                content["items"] = [
                    i for i in items if isinstance(i, dict) and (i.get("name") or "").strip()
                ]
            # 旧格式 categories：name 空且 items 空 → 移除
            categories = content.get("categories")
            if isinstance(categories, list):
                content["categories"] = [
                    c
                    for c in categories
                    if isinstance(c, dict) and ((c.get("name") or "").strip() or c.get("items"))
                ]
        elif mod.module_type in _ENTRY_MODULE_TYPES:
            # 兼容新格式 items 与旧格式 entries，两个字段都过滤全空条目
            for field in ("items", "entries"):
                field_items = content.get(field)
                if isinstance(field_items, list):
                    content[field] = [
                        i for i in field_items if isinstance(i, dict) and not _entry_is_blank(i)
                    ]
        elif mod.module_type in (ModuleType.OTHER, ModuleType.CUSTOM):
            if not (content.get("content") or "").strip():
                content["content"] = "未填写"
            # custom 的 title 也是必填（min_length=1），一并兜底
            if mod.module_type == ModuleType.CUSTOM and not (content.get("title") or "").strip():
                content["title"] = "未命名"


# ═══════════════════════════════════════════════════════════
# 读取
# ═══════════════════════════════════════════════════════════


async def get_resume_with_modules(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> tuple[Resume, list[ResumeModule]]:
    """获取简历 + 模块列表（校验归属）。

    Raises:
        HTTPException 404: 简历不存在或非本人
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

    modules_result = await db.execute(
        select(ResumeModule)
        .where(ResumeModule.resume_id == resume_id)
        .order_by(ResumeModule.sort_order, ResumeModule.id)
    )
    modules = list(modules_result.scalars().all())
    return resume, modules


# ═══════════════════════════════════════════════════════════
# 新建
# ═══════════════════════════════════════════════════════════


# 默认预置模块：请求未携带 modules 时固定 4 个核心模块，其余由用户按需添加。
# 注意 basic_info.name 必填（min_length=1），空壳用占位名"未命名"才能通过 content 校验。
_DEFAULT_MODULES: list[tuple[ModuleType, dict]] = [
    (ModuleType.BASIC_INFO, {"name": "未命名"}),
    (ModuleType.EDUCATION, {"items": []}),
    (ModuleType.WORK_EXPERIENCE, {"items": []}),
    (ModuleType.SKILLS, {"items": []}),
]


async def create_builder_resume(
    db: AsyncSession,
    user_id: int,
    body: BuilderCreateRequest,
) -> tuple[Resume, list[ResumeModule]]:
    """创建 builder 简历（source=builder, status=draft）+ 模块。

    流程：
    1. 确定模块列表：请求带 modules 用传入的；否则预置 4 个核心默认模块
    2. 校验每个模块 content
    3. 创建 Resume 行（source=builder, status=draft, parsed_text=""）
    4. 批量插入 ResumeModule

    Returns:
        (resume, modules)
    """
    # 1. 确定模块列表（无 modules 时预置默认模块）
    modules_input = body.modules
    if not modules_input:
        modules_input = [
            ResumeModuleCreate(module_type=module_type, content=content, sort_order=idx)
            for idx, (module_type, content) in enumerate(_DEFAULT_MODULES)
        ]

    # 2. 校验模块 content
    _validate_modules(modules_input)

    # 3. 创建 Resume
    resume = Resume(
        user_id=user_id,
        filename=body.filename,
        file_path="",  # builder 简历无上传文件
        parsed_text="",  # 草稿阶段无合并文本，T24 保存并完成时生成
        chunk_count=0,
        status="draft",
        source="builder",
        style=body.style.model_dump() if body.style else None,
        version=1,
    )
    db.add(resume)
    await db.flush()  # 拿到 resume.id

    # 4. 批量插入模块
    modules: list[ResumeModule] = []
    for idx, mod in enumerate(modules_input):
        module = ResumeModule(
            resume_id=resume.id,
            module_type=mod.module_type.value,
            content=mod.content,
            sort_order=mod.sort_order if mod.sort_order is not None else idx,
        )
        db.add(module)
        modules.append(module)

    await db.commit()
    await db.refresh(resume)
    for m in modules:
        await db.refresh(m)

    logger.info(
        "Created builder resume: user=%d, resume=%d, modules=%d",
        user_id,
        resume.id,
        len(modules),
    )
    return resume, modules


async def copy_resume_as_new(
    db: AsyncSession,
    user_id: int,
    source_resume_id: int,
    filename: str | None = None,
    language: str = "",
) -> tuple[Resume, list[ResumeModule]]:
    """复制一份简历为新草稿记录（含全部模块），用于多语言版本管理等。

 的「整份快照」思路，但存为**独立新简历**
    而非覆盖原稿——保证一份简历可同时保有中文/英文等多个语言版本。
    新副本 status=draft、version=1、content_hash/indexed_hash 为空（独立懒索引）。

    family 关联（多语言版本族）：副本 family_id = 源 resume.family_id or 源 resume.id
    （首个副本以源为族根，后续副本继承族），language 标注副本语言。
    """
    src = await db.get(Resume, source_resume_id)
    if src is None or src.user_id != user_id:
        raise HTTPException(status_code=404, detail="简历不存在或无权访问")

    mod_result = await db.execute(
        select(ResumeModule)
        .where(ResumeModule.resume_id == source_resume_id)
        .order_by(ResumeModule.sort_order, ResumeModule.id)
    )
    src_modules = mod_result.scalars().all()

    new_resume = Resume(
        user_id=user_id,
        filename=filename or f"{src.filename} 副本",
        file_path="",
        parsed_text=src.parsed_text or "",
        chunk_count=0,
        status="draft",
        source="builder",
        style=src.style,
        version=1,
        language=language or None,
        family_id=src.family_id or src.id,
    )
    db.add(new_resume)
    await db.flush()  # 拿到 new_resume.id

    new_modules: list[ResumeModule] = []
    for m in src_modules:
        module = ResumeModule(
            resume_id=new_resume.id,
            module_type=m.module_type,
            content=m.content,
            sort_order=m.sort_order,
        )
        db.add(module)
        new_modules.append(module)

    await db.commit()
    await db.refresh(new_resume)
    logger.info(
        "Copied resume: user=%d, src=%d -> copy=%d",
        user_id,
        source_resume_id,
        new_resume.id,
    )
    return new_resume, new_modules


# ═══════════════════════════════════════════════════════════
# 多语言翻译（新建语言版本后自动翻译副本）
# ═══════════════════════════════════════════════════════════

# 目标语言代码 → 语言名（prompt 用，与 react_agent TranslateTool 对齐）
_LANG_NAME_MAP: dict[str, str] = {
    "zh": "Chinese（中文）",
    "en": "English（英文）",
    "ja": "Japanese（日文）",
    "ko": "Korean（韩文）",
    "fr": "French（法文）",
    "de": "German（德文）",
}


def _parse_translated_modules(raw: str) -> list[dict]:
    """解析 LLM 输出的 JSON 数组，容忍 markdown 代码块围栏与前后缀文字。

    Raises:
        ValueError: 无法解析出有效 JSON 数组
    """
    text = raw.strip()
    # 剥离 ```json ... ``` / ``` ... ``` 围栏
    if text.startswith("```"):
        first = text.find("```")
        last = text.rfind("```")
        if last > first + 3:
            text = text[first + 3 : last]
        # 去掉围栏后可能残留的语言标记（如 json）
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    # 收紧到第一个 [ 与最后一个 ]（容忍 LLM 在前后加说明文字）
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("翻译结果不是 JSON 数组")
    return data


async def translate_resume_modules(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    target_lang: str,
) -> tuple[Resume, list[ResumeModule]]:
    """将简历全部模块内容翻译为目标语言，落库为草稿。

    多语言版本新建后自动翻译用（BuilderPage「新建英文版」等）：复制副本 → 翻译副本，
    用户跳转后直接得到目标语言版本。内容来源标注 inferred（AI 生成，需用户核对），
    与 G 可信度控制链路一致。

    规则：
    - 只更新 ResumeModule（删旧插新），不合并 parsed_text / content_hash——
      draft 阶段等「保存并完成」时统一从模块合并，避免翻译中间态污染检索内容
    - LLM 漏掉的模块用原文兜底（source=fact），保证不丢模块
    - 逐模块 validate_module_content 校验（结构不变，只翻译字符串值）

    Raises:
        HTTPException 404 简历不存在/无权访问；400 简历无模块；500 LLM 翻译或校验失败
    """
    from services.rag.pipeline import llm_generate
    from utils.privacy import sanitize_resume_module_for_ai

    resume, modules = await get_resume_with_modules(db, user_id, resume_id)
    if not modules:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="简历为空，无法翻译。请先在「编辑」页填写内容。",
        )

    lang_name = _LANG_NAME_MAP.get(target_lang, target_lang)
    modules_json = json.dumps(
        [
            {
                "module_type": m.module_type,
                "content": (
                    sanitize_resume_module_for_ai(m.module_type, m.content)
                    if isinstance(m.content, dict)
                    else m.content
                ),
                "sort_order": m.sort_order,
            }
            for m in modules
        ],
        ensure_ascii=False,
    )

    system = (
        f"你是专业简历翻译。请将用户提供的简历模块内容翻译为 {lang_name}。\n"
        "要求：\n"
        "1. 只翻译字符串值，保持 content 结构与字段一一对应，不增删字段、不增删 entries/categories/items\n"
        "2. 专业术语、专有名词（公司/学校/项目名、技术栈）保留原文或按惯例译出\n"
        "3. 遵守字段长度上限（basic_info.summary≤500、work_experience.description≤2000 等），翻译后不得超原上限\n"
        "4. 输出纯 JSON 数组，每项格式："
        '{"module_type": "...", "content": {...}, "sort_order": 0}\n'
        "5. 只输出 JSON，不要任何解释、前后缀或 markdown 代码块标记\n"
    )
    user = (
        f"目标语言：{lang_name}\n"
        f"当前简历模块：\n{modules_json}\n\n"
        f"请将全部模块内容翻译为 {lang_name}，输出 JSON 数组。"
    )

    try:
        raw = await llm_generate(
            system=system,
            user=user,
            temperature=0.2,
            max_tokens=8000,
            user_id=user_id,
            scenario="field_rewrite",
        )
        translated = _parse_translated_modules(raw)
    except Exception as e:
        logger.exception("Translate resume failed: resume=%d lang=%s", resume_id, target_lang)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"翻译失败：{e}",
        ) from e

    # 逐模块校验（只认有效模块，LLM 漏掉的用原文兜底）
    validated: list[dict] = []
    errors: list[str] = []
    for idx, item in enumerate(translated):
        if not isinstance(item, dict):
            errors.append(f"模块 {idx}: 不是对象")
            continue
        mt_str = item.get("module_type", "")
        content = item.get("content")
        sort_order = item.get("sort_order", idx)
        try:
            mt = ModuleType(mt_str)
            validate_module_content(mt, content)
        except (ValueError, ValidationError) as e:
            errors.append(f"模块 {idx} ({mt_str}): {e}")
            continue
        validated.append(
            {
                "module_type": mt_str,
                "content": content,
                "sort_order": sort_order if isinstance(sort_order, int) and sort_order >= 0 else idx,
                "source": "inferred",  # AI 翻译生成，需用户核对
            }
        )

    if not validated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="翻译结果校验失败：" + "; ".join(errors[:5]),
        )

    # LLM 漏掉的模块 → 原文兜底（不丢模块）
    out_types = {v["module_type"] for v in validated}
    for src_mod in modules:
        if src_mod.module_type not in out_types:
            validated.append(
                {
                    "module_type": src_mod.module_type,
                    "content": src_mod.content,
                    "sort_order": src_mod.sort_order,
                    "source": "fact",  # 原文，非 AI 生成
                }
            )

    # 删旧插新（source 标注；不合并 parsed_text，等 complete 统一处理）
    for old_mod in modules:
        await db.delete(old_mod)
    await db.flush()

    new_modules: list[ResumeModule] = []
    for v in sorted(validated, key=lambda x: x["sort_order"]):
        module = ResumeModule(
            resume_id=resume_id,
            module_type=v["module_type"],
            content=v["content"],
            sort_order=v["sort_order"],
            source=v["source"],
        )
        db.add(module)
        new_modules.append(module)

    resume.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(resume)
    for m in new_modules:
        await db.refresh(m)

    logger.info(
        "Translated resume: user=%d, resume=%d, lang=%s, modules=%d",
        user_id,
        resume_id,
        target_lang,
        len(new_modules),
    )
    return resume, new_modules


# ═══════════════════════════════════════════════════════════
# 草稿更新（last-write-wins）
# ═══════════════════════════════════════════════════════════


async def materialize_modules_from_text(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> tuple[Resume, list[ResumeModule], bool]:
    """懒物化：上传简历（source=upload）首次进 Builder 编辑器时，从 parsed_text 反解析生成模块。

    打通"上传（内容在 parsed_text）"→"Builder（内容在 ResumeModule）"两条内容源，
    让所有简历统一以模块为内容载体。

    规则：
    - 仅 source=upload 且无 ResumeModule 且 parsed_text 非空才物化
    - 物化成功后 resume.source → "builder"（标记已物化，避免重复 LLM 调用）
    - 物化不修改 parsed_text / content_hash（检索仍用原解析文本，直到用户 complete）
    - 反解析失败 → 返回 (空模块, False)，不抛异常，由调用方降级提示（粘贴导入）

    Returns:
        (resume, modules, materialized) — materialized=True 表示简历可用模块编辑
        （已物化过或本次物化成功）；False 表示物化失败（空模块 + 需降级提示）。
    """
    from services.resume_parser import parse_text_to_modules

    resume, modules = await get_resume_with_modules(db, user_id, resume_id)

    # 已物化（builder 简历或有模块）或无文本 → 直接返回
    if resume.source != "upload" or modules or not resume.parsed_text:
        return resume, modules, True

    try:
        parsed = await parse_text_to_modules(
            resume.parsed_text,
            user_id=user_id,
            source_filename=resume.filename,
        )
    except Exception as e:  # noqa: BLE001 LLM/校验失败 → 降级，不抛给用户
        logger.warning("懒物化失败（可降级粘贴导入）resume=%d: %s", resume_id, e)
        return resume, modules, False

    # 并发安全：LLM 调用耗时较长，期间可能有其他请求已物化成功。
    # 提交前重新检查，避免失败的请求覆盖成功的结果。
    check_result = await db.execute(
        select(ResumeModule).where(ResumeModule.resume_id == resume_id).limit(1)
    )
    if check_result.scalar_one_or_none() is not None:
        logger.info("懒物化被其他请求抢先完成，跳过 resume=%d", resume_id)
        await db.rollback()
        refreshed, refreshed_mods = await get_resume_with_modules(db, user_id, resume_id)
        return refreshed, refreshed_mods, True

    new_modules: list[ResumeModule] = []
    for idx, mod in enumerate(parsed):
        module = ResumeModule(
            resume_id=resume_id,
            module_type=mod.module_type.value,
            content=mod.content,
            sort_order=mod.sort_order if mod.sort_order is not None else idx,
        )
        db.add(module)
        new_modules.append(module)

    resume.source = "builder"  # 标记已物化，避免重复 LLM
    await db.commit()
    await db.refresh(resume)
    for m in new_modules:
        await db.refresh(m)

    logger.info("懒物化完成 resume=%d modules=%d", resume_id, len(new_modules))
    return resume, new_modules, True


async def update_resume_draft(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    body: BuilderDraftUpdateRequest,
) -> tuple[Resume, list[ResumeModule]]:
    """草稿更新（last-write-wins，不查 version）。

    spec A5#66: 草稿自动保存用 last-write-wins（不查 version、不 bump）。
    spec F: PUT mode=draft 不带 version。

    规则：
    - 仅 draft / ready 状态可草稿更新（非 draft/ready → 409）
    - 保存草稿后 status 置为 draft（内容已变但未"保存并完成"，不再视为已就绪）
    - modules: 全量替换（先删后插）
    - style / filename: 可选部分更新
    - version 不变

    Returns:
        (resume, modules)
    """
    resume, existing_modules = await get_resume_with_modules(db, user_id, resume_id)

    # 仅 draft / ready 状态可草稿更新（编辑上传/已完成简历时自动保存草稿也应可用）
    if resume.status not in ("draft", "ready"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"仅草稿或已就绪简历可草稿保存（当前状态: {resume.status}）",
        )

    # 1. 部分更新字段
    if body.filename is not None:
        resume.filename = body.filename
    if body.style is not None:
        resume.style = body.style.model_dump()

    # 2. 全量替换模块（如果请求体包含 modules）
    new_modules: list[ResumeModule] = []
    if body.modules is not None:
        # 草稿保存宽容化：清理编辑中间态空值（数据清洁，移除全空条目/空分类）
        _sanitize_draft_modules(body.modules)
        # 草稿宽松校验：容忍编辑中间态（字段完整性由保存并完成时严格把关）
        _validate_modules(body.modules, strict=False)

        # 删旧模块
        for old_mod in existing_modules:
            await db.delete(old_mod)
        await db.flush()

        # 插新模块
        for idx, mod in enumerate(body.modules):
            module = ResumeModule(
                resume_id=resume_id,
                module_type=mod.module_type.value,
                content=mod.content,
                sort_order=mod.sort_order if mod.sort_order is not None else idx,
            )
            db.add(module)
            new_modules.append(module)

    # (D3 草稿工作区隔离)：草稿保存不更新 content_hash（parsed_text 未变 → 检索内容未变），
    # 不置脏也不触发索引；内容变更发生在 complete（重新合并 parsed_text 后统一算 hash）。

    # version 不变（last-write-wins）
    # 内容已修改但未"保存并完成"重建索引 → 不再视为已就绪，置为 draft
    await set_resume_status(db, resume, "draft", reason="草稿保存")
    resume.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(resume)

    # 如果没替换模块，返回已有模块
    if not new_modules and body.modules is None:
        new_modules = existing_modules
        # refresh existing modules（session 可能 expired）
        for m in new_modules:
            await db.refresh(m)
    else:
        for m in new_modules:
            await db.refresh(m)

    logger.info(
        "Updated resume draft: user=%d, resume=%d, modules=%d",
        user_id,
        resume_id,
        len(new_modules),
    )
    return resume, new_modules


# ═══════════════════════════════════════════════════════════
# 保存并完成（T24: 乐观锁 → 合并 parsed_text → drop/rebuild Chroma → ready）
# ═══════════════════════════════════════════════════════════

# module_type → 简历节段标题（对齐 chunking.py SECTION_HEADERS）
_MODULE_SECTION_HEADERS: dict[str, str] = {
    "basic_info": "个人简介",
    "education": "教育背景",
    "work_experience": "工作经历",
    "project_experience": "项目经历",
    "skills": "专业技能",
    "language": "语言能力",
    "honors": "荣誉",
    "certificates": "证书",
    "interests": "兴趣爱好",
    "club_activities": "社团活动",
    "publications": "研究成果",
    "recommendation": "推荐人",
    "social_links": "社交链接",
    "other": "其他",
    "custom": "自定义",
}

# content JSON key → 中文标签
_FIELD_LABELS: dict[str, str] = {
    "name": "姓名",
    "phone": "手机",
    "email": "邮箱",
    "gender": "性别",
    "age": "年龄",
    "location": "所在城市",
    "avatar": "头像",
    "job_title": "求职意向",
    "summary": "个人总结",
    "status": "当前状态",
    "hometown": "籍贯",
    "work_years": "工作年限",
    "highest_education": "最高学历",
    "homepage_url": "个人主页",
    "github_url": "GitHub",
    "blog_url": "技术博客",
    "custom_fields": "自定义信息",
    "school": "学校",
    "degree": "学历",
    "major": "专业",
    "start_date": "开始时间",
    "end_date": "结束时间",
    "gpa": "GPA",
    "description": "描述",
    "company": "公司",
    "position": "职位",
    "achievements": "主要成就",
    "role": "角色",
    "url": "链接",
    "tech_stack": "技术栈",
    "proficiency": "熟练度",
    "score": "成绩",
    "title": "标题",
    "issuer": "颁发机构",
    "date": "时间",
    "authors": "作者",
    "venue": "发表期刊",
    "organization": "组织",
    "contact": "联系方式",
    "github": "GitHub",
    "linkedin": "LinkedIn",
    "website": "个人网站",
    "twitter": "Twitter",
    "wechat": "微信",
    "content": "内容",
}

_MODULE_FIELD_LABELS: dict[str, dict[str, str]] = {
    "project_experience": {"name": "项目名称"},
    "skills": {"name": "技能"},
    "language": {"name": "语言"},
    "honors": {"title": "奖项名称"},
    "certificates": {"name": "证书名称"},
    "interests": {"name": "兴趣"},
    "club_activities": {"name": "社团/活动"},
    "publications": {"title": "成果标题"},
    "recommendation": {"name": "推荐人"},
    "social_links": {"platform": "平台"},
}


def _label(key: str, module_type: str | None = None) -> str:
    """获取字段中文标签，无映射时返回原 key。"""
    if module_type:
        module_label = _MODULE_FIELD_LABELS.get(module_type, {}).get(key)
        if module_label:
            return module_label
    return _FIELD_LABELS.get(key, key)


def _format_value(value, module_type: str | None = None) -> str:
    """格式化值为字符串。"""
    if value is None:
        return ""
    if isinstance(value, list):
        if all(isinstance(i, str) for i in value):
            return ", ".join(value)
        return ", ".join(
            _entry_to_text(i, module_type) if isinstance(i, dict) else str(i) for i in value
        )
    if isinstance(value, dict):
        return _entry_to_text(value, module_type)
    return str(value)


def _entry_to_text(entry: dict, module_type: str | None = None) -> str:
    """将单条 entry（dict）转为一行文本，字段用 | 分隔。"""
    parts = []
    for k, v in entry.items():
        # id/hidden 是编辑器元数据，不属于候选人简历正文。
        if k in {"id", "hidden", "metadata"}:
            continue
        if v is not None and v != "" and v != []:
            parts.append(f"{_label(k, module_type)}: {_format_value(v, module_type)}")
    return " | ".join(parts)


def _module_content_to_text(module_type: str, content: dict) -> str:
    """将单个模块的 content JSON 转为可读文本。

    格式策略：
    - 列表型模块（entries）: 每条一行，字段用 | 分隔
    - 技能模块（categories）: 分类名: 技能1, 技能2
    - 兴趣模块（items）: 兴趣1, 兴趣2
    - 平铺型模块（basic_info 等）: 字段名: 值
    """
    metadata = content.get("metadata")
    if isinstance(metadata, dict) and metadata.get("hidden") is True:
        return ""

    # v2 统一结构：教育、工作、项目、技能等列表模块均使用 items。
    # 旧实现只识别 entries/categories，导致页面表单与 parsed_text 严重不一致。
    items = content.get("items")
    if isinstance(items, list):
        lines: list[str] = []
        for item in items:
            if isinstance(item, dict):
                if item.get("hidden") is True:
                    continue
                line = _entry_to_text(item, module_type)
            else:
                line = _format_value(item, module_type)
            if line.strip():
                lines.append(line)
        return "\n".join(lines)

    # 兼容 v1 列表结构。
    if "entries" in content and isinstance(content["entries"], list):
        lines = []
        for entry in content["entries"]:
            if isinstance(entry, dict):
                lines.append(_entry_to_text(entry, module_type))
        return "\n".join(lines)

    # 技能模块
    if "categories" in content and isinstance(content["categories"], list):
        lines = []
        for cat in content["categories"]:
            if isinstance(cat, dict):
                name = cat.get("name", "")
                items = ", ".join(cat.get("items", []))
                if items:
                    lines.append(f"{name}: {items}")
        return "\n".join(lines)

    # 平铺型模块（basic_info, social_links, other, custom）
    lines = []
    for k, v in content.items():
        if k in {"metadata", "hidden"}:
            continue
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    if item.get("hidden") is True:
                        continue
                    line = _entry_to_text(item, module_type)
                    if line:
                        lines.append(line)
                elif item not in (None, ""):
                    lines.append(_format_value(item, module_type))
        else:
            lines.append(f"{_label(k, module_type)}: {_format_value(v, module_type)}")
    return "\n".join(lines)


def _merge_modules_to_text(modules: list[ResumeModule]) -> str:
    """将模块列表合并为纯文本（用于向量化）。

    每个模块用节段标题分隔，标题对齐 chunking.py 的 SECTION_HEADERS，
    确保分块器能正确识别节段边界。
    """
    parts = []
    for mod in sorted(modules, key=lambda m: (m.sort_order, m.id)):
        header = _MODULE_SECTION_HEADERS.get(mod.module_type, mod.module_type)
        content_text = _module_content_to_text(mod.module_type, mod.content)
        if content_text.strip():
            parts.append(f"{header}\n{content_text}")
    return "\n\n".join(parts)


def _enrich_derived_fields(modules: list[ResumeModule]) -> None:
    """派生字段增强（SmartResume data_processor 对照，直接复制其纯函数）。

    - work_experience.items[].company → clean_company_name（重复后缀折叠）
    - education.items[].school → clean_school_name（去括号）
    - basic_info：缺失时补 work_years / highest_education（derive_work_years /
      derive_highest_education），age/gpa 若存在则做范围校验清洗
    - 不改 parsed_text（派生字段不入检索原文，避免污染向量内容）
    """
    from services.derived_fields import (
        clean_company_name,
        clean_school_name,
        derive_highest_education,
        derive_work_years,
        extract_age,
        extract_gpa,
    )

    work_items: list[dict] = []
    edu_items: list[dict] = []
    basic: dict | None = None

    for m in modules:
        content = m.content or {}
        if m.module_type == "work_experience":
            for it in content.get("items", []) or []:
                if isinstance(it, dict) and it.get("company"):
                    it["company"] = clean_company_name(it["company"])
                    work_items.append(it)
        elif m.module_type == "education":
            for it in content.get("items", []) or []:
                if isinstance(it, dict):
                    if it.get("school"):
                        it["school"] = clean_school_name(it["school"])
                    edu_items.append(it)
        elif m.module_type == "basic_info":
            basic = content

    if basic is None:
        return
    # 缺失时补派生字段（不覆盖用户显式填写值）
    if basic.get("work_years") is None:
        wy = derive_work_years(work_items, edu_items)
        if wy >= 0:
            basic["work_years"] = wy
    if not basic.get("highest_education"):
        he = derive_highest_education(edu_items)
        if he:
            basic["highest_education"] = he
    # 范围校验清洗（SmartResume 年龄/GPA 提取对照）
    if basic.get("age") is not None:
        age = extract_age(basic["age"])
        if age >= 0:
            basic["age"] = age
    if basic.get("gpa") is not None:
        gpa = extract_gpa(basic["gpa"])
        if gpa >= 0:
            basic["gpa"] = gpa


async def complete_resume(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    body: BuilderUpdateRequest,
) -> tuple[Resume, list[ResumeModule]]:
    """保存并完成（乐观锁 → 合并 parsed_text → drop/rebuild Chroma → ready）。

    spec B#19: 草稿 → 保存并完成 → 生成 parsed_text + 向量化 → ready。
    spec F: PUT mode=complete 必带 version（乐观锁）。

    流程：
    1. 校验归属 + 获取简历和模块
    2. 乐观锁校验（version 不匹配 → 409）
    3. 状态校验（仅 draft/ready 可完成，processing/failed → 409）
    4. 如果请求体包含 modules，校验 + 全量替换
    5. 部分更新 filename / style
    6. 合并所有模块 → parsed_text + content_hash（D3 脏标记）
    7. 清 embedding 缓存（旧缓存对应旧文本）
    8. 版本化重建（ensure_indexed → index_asset，D2 版本快照 + 旧版本保留）
    9. 更新 resume: chunk_count, status=ready, version+=1
    10. commit

    幂等性：index_asset 旧版本 chunks 置 is_latest=False 保留，新版本可查，重复调用不残留脏块。

    Returns:
        (resume, modules)

    Raises:
        HTTPException 404: 简历不存在或非本人
        HTTPException 409: version 不匹配 / 状态不允许
        HTTPException 422: version 缺失 / 模块校验失败
        HTTPException 500: 向量化重建失败
    """
    resume, existing_modules = await get_resume_with_modules(db, user_id, resume_id)

    # 1. 乐观锁校验
    if body.version is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="mode=complete 时 version 必填",
        )
    if body.version != resume.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"版本冲突：当前版本 {resume.version}，请求版本 {body.version}",
        )

    # 2. 状态校验（processing/failed 不允许完成）
    if resume.status not in ("draft", "ready"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"仅草稿或已就绪简历可保存并完成（当前状态: {resume.status}）",
        )

    # 3. 部分更新字段
    if body.filename is not None:
        resume.filename = body.filename
    if body.style is not None:
        resume.style = body.style.model_dump()

    # 4. 全量替换模块（如果请求体包含 modules）
    current_modules = existing_modules
    if body.modules is not None:
        # 完成态必须经过严格校验；草稿阶段的占位/空条目清洗不能带入
        # complete，否则空姓名会被伪装成“未命名”而绕过最终校验。
        _validate_modules(body.modules)

        for old_mod in existing_modules:
            await db.delete(old_mod)
        await db.flush()

        current_modules = []
        for idx, mod in enumerate(body.modules):
            module = ResumeModule(
                resume_id=resume_id,
                module_type=mod.module_type.value,
                content=mod.content,
                sort_order=mod.sort_order if mod.sort_order is not None else idx,
            )
            db.add(module)
            current_modules.append(module)

    # 4.5 派生字段增强：公司/校名清洗 + 工作年限/最高学历推导（缺失时补）
    try:
        _enrich_derived_fields(current_modules)
    except Exception as e:
        logger.warning("派生字段增强失败（不影响主流程）: %s", e)

    # 5. 合并模块 → parsed_text + content_hash（content_hash 统一 = hash(parsed_text)，与上传语义一致）
    # 兜底：请求未带 modules 且简历无模块（如上传简历绕过编辑器直调 complete）→ 保留原解析文本
    if body.modules is None and not current_modules and resume.parsed_text:
        parsed_text = resume.parsed_text
    else:
        parsed_text = _merge_modules_to_text(current_modules)
        resume.parsed_text = parsed_text
    previous_content_hash = resume.content_hash
    resume.content_hash = hashlib.sha256(parsed_text.encode("utf-8")).hexdigest()

    # 6. 清派生缓存。分析缓存和向量缓存都对应旧正文；若只清向量缓存，
    # 用户保存新表单后仍会收到旧诊断/旧评分。
    from services.resume_analysis_cache import invalidate_resume_cache

    if resume.content_hash != previous_content_hash:
        await invalidate_resume_cache(resume_id)
    await embedding_cache.clear_resume(resume_id)

    # 7. 版本化重建（ensure_indexed：懒索引/预热统一入口，D2/D3）
    try:
        indexed = await ensure_indexed(
            db,
            user_id=user_id,
            asset_id=resume_id,
            asset_type=ASSET_TYPE_RESUME,
            collection=knowledge_collection_name(user_id),
        )
        if not indexed:
            raise RuntimeError("ensure_indexed failed")
    except Exception as e:
        logger.exception("Failed to rebuild vectors for resume %d", resume_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="向量化重建失败，请稍后重试",
        ) from e

    # 8. 更新 resume（chunk_count 已由 ensure_indexed 重建写回；未重建时是上次值，内容未变故正确）
    from services.resume_service import set_resume_status

    await set_resume_status(db, resume, "ready", reason="保存并完成")
    resume.version += 1
    resume.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(resume)

    for m in current_modules:
        await db.refresh(m)

    logger.info(
        "Completed resume: user=%d, resume=%d, chunks=%d, version=%d",
        user_id,
        resume_id,
        resume.chunk_count,
        resume.version,
    )
    return resume, current_modules
