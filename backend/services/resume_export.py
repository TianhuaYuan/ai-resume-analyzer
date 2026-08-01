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
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.resume import Resume
from models.resume_module import ResumeModule
from schemas.resume_module import ResumeStyle
from services.resume_builder import _merge_modules_to_text, _MODULE_SECTION_HEADERS
from services.resume_template import render_resume

logger = logging.getLogger(__name__)

# WeasyPrint 懒导入（GTK 未安装时不可用）
_weasyprint = None
_weasyprint_checked = False


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

    # 列表型模块
    if "entries" in content and isinstance(content["entries"], list):
        for entry in content["entries"]:
            if isinstance(entry, dict):
                parts = []
                for k, v in entry.items():
                    if v is None or v == "" or v == []:
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

    # 技能模块
    if "categories" in content and isinstance(content["categories"], list):
        for cat in content["categories"]:
            if isinstance(cat, dict):
                name = cat.get("name", "")
                items = cat.get("items", [])
                if items:
                    lines.append(f"- **{name}**: {', '.join(items)}")
        lines.append("")
        return "\n".join(lines)

    # 兴趣模块
    if "items" in content and isinstance(content["items"], list) and all(
        isinstance(i, str) for i in content["items"]
    ):
        lines.append(", ".join(content["items"]))
        lines.append("")
        return "\n".join(lines)

    # 平铺型模块
    for k, v in content.items():
        if v is None or v == "" or v == []:
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

    # 构建 Markdown
    lines = [
        f"# {resume.filename}",
        "",
        f"> 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
    ]

    for mod in sorted(modules, key=lambda m: (m.sort_order, m.id)):
        lines.append(_module_to_markdown(mod))

    lines.append("---")
    lines.append("")
    lines.append("*由 AI Resume Analyzer 生成*")

    markdown = "\n".join(lines)
    filename = f"resume_{resume_id}.md"
    logger.info("Exported Markdown: resume=%d, size=%d chars", resume_id, len(markdown))
    return markdown, filename
