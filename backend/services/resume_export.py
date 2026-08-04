"""T26: 简历导出服务 — PDF + Markdown + 零模块守卫。

职责：
- export_resume_pdf: 用 WeasyPrint 将 render_resume HTML → PDF bytes
- export_resume_markdown: 从 resume_modules 拼接 Markdown 文本
- _guard_has_modules: 零模块守卫（无模块 → 422）

设计依据：
- plan.md T26: WeasyPrint PDF + Markdown（从 resume_modules 拼）+ 零模块守卫
- plan.md 风险表: WeasyPrint CSS 兼容 → T25 服务端预解析变量
- spec: 头像上传白名单/MIME/5MB/PIL/uuid（本模块不含头像，头像在 avatar_service）
"""

import io
import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.resume import Resume
from models.resume_module import ResumeModule
from schemas.resume_module import ResumeStyle, get_content_items
from services.resume_builder import _merge_modules_to_text, _MODULE_SECTION_HEADERS
from services.resume_template import render_resume

logger = logging.getLogger(__name__)

# WeasyPrint 懒导入（GTK 未安装时不可用）
_weasyprint = None
_weasyprint_checked = False

# 匹配 /uploads/... 图片 URL（JPG/PNG/WebP）
_UPLOAD_URL_RE = re.compile(r'/uploads/[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)', re.IGNORECASE)


def _get_weasyprint():
    """懒加载 WeasyPrint，GTK 缺失时返回 None。"""
    global _weasyprint, _weasyprint_checked
    if _weasyprint_checked:
        return _weasyprint
    _weasyprint_checked = True
    try:
        from weasyprint import HTML
        _weasyprint = HTML
        logger.info("WeasyPrint loaded successfully")
    except (ImportError, OSError) as e:
        logger.warning("WeasyPrint not available: %s", e)
        _weasyprint = None
    return _weasyprint


def _resolve_upload_urls(html: str) -> str:
    """将 HTML 中 /uploads/... 相对 URL 替换为 file:// 绝对路径。

    WeasyPrint 在服务器端渲染，无法通过 HTTP 访问相对路径的图片。
    将 /uploads/avatars/xxx.jpg → file:///app/uploads/avatars/xxx.jpg
    """
    from core.config import settings

    uploads_base = Path(settings.UPLOAD_DIR).resolve()  # e.g. /app/uploads

    def _replace(match: re.Match) -> str:
        rel_path = match.group(0).lstrip("/")  # uploads/avatars/xxx.jpg
        abs_path = uploads_base.parent / rel_path  # /app/uploads/avatars/xxx.jpg
        return f"file://{abs_path}"

    return _UPLOAD_URL_RE.sub(_replace, html)


# ═══════════════════════════════════════════════════════════
# 零模块守卫
# ═══════════════════════════════════════════════════════════


def _guard_has_modules(modules: list[ResumeModule], resume: Resume | None = None) -> None:
    """零模块守卫 — 无模块时抛 422。

    spec 边界 13: 仅对 source=upload 且 resume_modules 为空 的简历返回提示（防空白导出）。
    builder 简历即使空模块也允许渲染/预览空模板，不拦截（#7 修复预览 422）。
    """
    if not modules or len(modules) == 0:
        if resume is not None and getattr(resume, "source", "") == "builder":
            return
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="简历没有任何模块内容，无法导出。请先添加模块后再导出。",
        )


# ═══════════════════════════════════════════════════════════
# PDF 导出
# ═══════════════════════════════════════════════════════════


async def export_resume_pdf(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> tuple[bytes, str]:
    """导出简历为 PDF。

    流程：
    1. 获取简历 + 模块（校验归属）
    2. 零模块守卫
    3. render_resume 渲染 HTML（含 CSS 变量预解析）
    4. WeasyPrint HTML → PDF

    Returns:
        (pdf_bytes, filename)

    Raises:
        HTTPException 404: 简历不存在或非本人
        HTTPException 422: 零模块
        HTTPException 503: WeasyPrint 不可用（GTK 未安装）
    """
    from services.resume_builder import get_resume_with_modules
    resume, modules = await get_resume_with_modules(db, user_id, resume_id)
    _guard_has_modules(modules, resume)

    # 解析 style（防御历史脏数据：style 可能是双重序列化的 JSON 字符串）
    style = ResumeStyle.from_db(resume.style)

    # 渲染 HTML
    html_str = render_resume(modules, style, resume.filename)

    # 将 /uploads/... URL 解析为绝对文件路径（WeasyPrint 无法访问相对 URL）
    html_str = _resolve_upload_urls(html_str)

    # WeasyPrint → PDF
    HTML = _get_weasyprint()
    if HTML is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF 导出服务不可用（服务器未安装 WeasyPrint/GTK 运行时）。请使用 Markdown 导出。",
        )

    try:
        pdf_buffer = io.BytesIO()
        HTML(string=html_str).write_pdf(pdf_buffer)
        pdf_bytes = pdf_buffer.getvalue()
    except Exception as e:
        logger.exception("PDF generation failed for resume %d", resume_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PDF 生成失败，请稍后重试",
        ) from e

    filename = f"resume_{resume_id}.pdf"
    logger.info("Exported PDF: resume=%d, size=%d bytes", resume_id, len(pdf_bytes))
    return pdf_bytes, filename


# ═══════════════════════════════════════════════════════════
# Markdown 导出
# ═══════════════════════════════════════════════════════════

# module_type → Markdown 节标题
_MD_SECTION_TITLES: dict[str, str] = _MODULE_SECTION_HEADERS


def _module_to_markdown(mod: ResumeModule) -> str:
    """将单个模块转为 Markdown 段落。"""
    title = _MD_SECTION_TITLES.get(mod.module_type, mod.module_type)
    content = mod.content if isinstance(mod.content, dict) else {}

    lines = [f"## {title}", ""]

    # 纯字符串 items（兴趣/标签等）—— 直接逗号拼接（须先于通用 dict 列表分支，否则被跳过）
    if "items" in content and isinstance(content["items"], list) and all(
        isinstance(i, str) for i in content["items"]
    ):
        lines.append(", ".join(content["items"]))
        lines.append("")
        return "\n".join(lines)

    # 列表型模块（v2: items；兼容旧格式 entries / skills categories）
    items = get_content_items(content)
    if isinstance(items, list) and items:
        for item in items:
            if isinstance(item, dict):
                parts = []
                for k, v in item.items():
                    if v is None or v == "" or v == [] or k in ("id", "hidden"):
                        continue
                    if isinstance(v, list):
                        v_text = ", ".join(str(i) for i in v)
                    else:
                        v_text = str(v)
                    parts.append(f"**{k}**: {v_text}")
                if parts:
                    lines.append(f"- {' | '.join(parts)}")
        lines.append("")
        return "\n".join(lines)

    # 技能模块（v2: 扁平 items 按 category 分组）
    if isinstance(items, list) and items and isinstance(items[0], dict) and "category" in items[0]:
        grouped: dict[str, list[str]] = {}
        for item in items:
            cat = item.get("category", "其他")
            name = item.get("name", "")
            if name:
                grouped.setdefault(cat, []).append(name)
        for cat_name, skill_names in grouped.items():
            lines.append(f"- **{cat_name}**: {', '.join(skill_names)}")
        lines.append("")
        return "\n".join(lines)

    # 平铺型模块
    for k, v in content.items():
        if v is None or v == "" or v == []:
            continue
        # 跳过头像 URL（二进制资源，Markdown 中无意义）
        if k == "avatar":
            continue
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    name = item.get("name", "")
                    url = item.get("url", "")
                    if name or url:
                        lines.append(f"- **{name}**: {url}")
        else:
            lines.append(f"**{k}**: {v}")
    lines.append("")
    return "\n".join(lines)


async def export_resume_markdown(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> tuple[str, str]:
    """导出简历为 Markdown。

    从 resume_modules 拼接 Markdown 文本，不依赖 WeasyPrint。

    Returns:
        (markdown_str, filename)

    Raises:
        HTTPException 404: 简历不存在或非本人
        HTTPException 422: 零模块
    """
    from services.resume_builder import get_resume_with_modules
    resume, modules = await get_resume_with_modules(db, user_id, resume_id)
    _guard_has_modules(modules, resume)

    # 解析 style（防御历史脏数据：style 可能是双重序列化的 JSON 字符串）
    style = ResumeStyle.from_db(resume.style)

    # 构建 Markdown
    lines = [
        f"# {resume.filename}",
        "",
        f"> 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
    ]

    hidden_modules = set(style.hidden_modules or [])
    for mod in sorted(modules, key=lambda m: (m.sort_order, m.id)):
        if mod.module_type in hidden_modules:
            continue
        lines.append(_module_to_markdown(mod))

    lines.append("---")
    lines.append("")
    lines.append("*由 AI Resume Analyzer 生成*")

    markdown = "\n".join(lines)
    filename = f"resume_{resume_id}.md"
    logger.info("Exported Markdown: resume=%d, size=%d chars", resume_id, len(markdown))
    return markdown, filename
