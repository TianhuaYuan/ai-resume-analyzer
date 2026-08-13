"""ATS 可读性模拟审计服务 — 纯本地规则引擎，零 LLM。

职责：
- 模拟 ATS 解析简历，检出乱码段/空白段/特殊符号/图片文字/表格等问题
- 双路径审计：HTML 直读（始终执行）+ PDF 回读（WeasyPrint 可用时追加）
- 返回结构化问题清单 + 得分

设计依据：
- plan P0-A：ATS 可读性模拟（国内 Boss/牛客上传踩坑场景）
- 复用 file_parser.py 的 _GARBLED_PATTERN / _is_garbled
- 复用 resume_template.py 的 render_resume
- 复用 resume_export.py 的 export_resume_pdf / _get_weasyprint
"""

import io
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.resume import (
    AtsAuditIssue,
    AtsAuditResponse,
    AtsIssueType,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 乱码检测（复用 resume_parser.py 的模式）
# ═══════════════════════════════════════════════════════════

# PDF 水印/损坏字体的长字母数字串特征（来自 SmartResume should_remove）
_GARBLED_PATTERN = re.compile(r"[a-zA-Z0-9\-~_]{40,}")

# Unicode 替换字符（解码失败占位符）
_REPLACEMENT_CHAR = "�"

# 控制字符（C0 + DEL + C1，排除 \t \n \r）
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]")

# 连续空行（2 行及以上）
_CONSECUTIVE_BLANK_RE = re.compile(r"\n{3,}")

# 装饰性特殊符号
_SPECIAL_SYMBOL_RE = re.compile(
    r"[●◆★☆▪▫■□▲△▼▽♠♣♥♦✦✧❖⟐⟑★☆⚡✦✧]"
)

# Emoji 范围（常见 emoji 补充范围）
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # ZWJ
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002B50-\U00002B55"  # stars
    "\U0000231A-\U0000231B"
    "\U000023E9-\U000023F3"
    "\U000023F8-\U000023FA"
    "\U00002934-\U00002935"
    "\U000025AA-\U000025AB"
    "\U000025B6"
    "\U000025C0"
    "\U000025FB-\U000025FE"
    "\U00002B05-\U00002B07"
    "\U00002B1B-\U00002B1C"
    "\U00003030"
    "\U0000303D"
    "\U00003297"
    "\U00003299"
    "]"
)

# 竖线分隔符（表格布局滥用检测）
_PIPE_RE = re.compile(r"\|")


def _is_garbled(s: str) -> bool:
    """乱码判定（SmartResume should_remove 的无 tiktoken 等价）。

    乱码每个字符一个 token，BPE token 数 > 字符数*0.5。
    简化判断：纯 ASCII 长串（>40）+ 无空格 + 无中文 → 可能是乱码。
    """
    if len(s) < 40:
        return False
    # 有空格说明是正常文本
    if " " in s:
        return False
    # 有中文说明是正常文本
    if any("一" <= c <= "鿿" for c in s):
        return False
    # 长纯 ASCII 无空格无中文 → 大概率乱码（PDF 水印/损坏字体）
    return True


# ═══════════════════════════════════════════════════════════
# HTML 解析器（从 render_resume 输出中提取各节文本）
# ═══════════════════════════════════════════════════════════


class _HtmlSectionParser(HTMLParser):
    """按 h2.module-title 切分 HTML 为节段，提取纯文本内容。"""

    def __init__(self):
        super().__init__()
        self._sections: list[dict[str, str]] = []
        self._current_section: str | None = None
        self._in_script: bool = False
        self._in_style: bool = False
        self._in_h2: bool = False
        self._in_title: bool = False  # module-title h2
        self._text_buf: list[str] = []
        self._title_buf: list[str] = []
        self._current_text: list[str] = []
        self._title_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "script":
            self._in_script = True
            return
        if tag == "style":
            self._in_style = True
            return
        if tag == "h2":
            attrs_dict = dict(attrs)
            classes = attrs_dict.get("class", "")
            if "module-title" in classes:
                self._in_h2 = True
                self._in_title = True
                self._title_buf = []
        # section 标签（模块开始）—— 可选辅助
        if tag in ("section", "div") and self._current_section is None:
            attrs_dict = dict(attrs)
            classes = attrs_dict.get("class", "")
            if "module-" in classes:
                # 尝试从 class 提取 module_type
                for cls in classes.split():
                    if cls.startswith("module-") and cls != "module-title" and cls != "module-content":
                        break

    def handle_endtag(self, tag: str):
        if tag == "script":
            self._in_script = False
            return
        if tag == "style":
            self._in_style = False
            return
        if tag == "h2" and self._in_h2:
            self._in_h2 = False
            self._in_title = False
            title = "".join(self._title_buf).strip()
            if title:
                # 保存上一个 section 的内容
                if self._current_section is not None:
                    self._sections.append({
                        "section": self._current_section,
                        "text": "\n".join(self._current_text).strip(),
                    })
                self._current_section = title
                self._current_text = []
            self._title_buf = []

    def handle_data(self, data: str):
        if self._in_script or self._in_style:
            return
        if self._in_title:
            self._title_buf.append(data)
            return
        if self._current_section is not None:
            self._current_text.append(data)

    def get_sections(self) -> list[dict[str, str]]:
        """获取解析后的节段列表。"""
        # 处理最后一个 section
        if self._current_section is not None:
            self._sections.append({
                "section": self._current_section,
                "text": "\n".join(self._current_text).strip(),
            })
        return self._sections


# ═══════════════════════════════════════════════════════════
# 规则扫描函数（纯函数）
# ═══════════════════════════════════════════════════════════


@dataclass
class _ScanResult:
    """扫描结果。"""
    issues: list[AtsAuditIssue] = field(default_factory=list)


def _scan_garbled(text: str, section: str = "全文") -> list[AtsAuditIssue]:
    """扫描乱码文本。

    检测：
    1. _GARBLED_PATTERN 匹配的长字母数字串 + _is_garbled 确认
    2. Unicode 替换字符 �
    3. 控制字符
    """
    issues: list[AtsAuditIssue] = []

    # 1. 长字母数字串乱码
    for match in _GARBLED_PATTERN.finditer(text):
        candidate = match.group(0)
        if _is_garbled(candidate):
            context_start = max(0, match.start() - 20)
            context_end = min(len(text), match.end() + 20)
            issues.append(AtsAuditIssue(
                section=section,
                issue_type=AtsIssueType.garbled,
                severity="high",
                message=f"检测到疑似乱码文本（{len(candidate)} 字符）",
                suggestion="检查 PDF 字体嵌入是否完整，或尝试重新导出为文本格式",
                context=text[context_start:context_end].strip(),
            ))

    # 2. Unicode 替换字符
    replacement_count = text.count(_REPLACEMENT_CHAR)
    if replacement_count > 0:
        issues.append(AtsAuditIssue(
            section=section,
            issue_type=AtsIssueType.garbled,
            severity="high",
            message=f"检测到 {replacement_count} 个 Unicode 替换字符（），表明编码错误",
            suggestion="检查文件编码，确保使用 UTF-8 编码保存",
            context=None,
        ))

    # 3. 控制字符（排除常见的 \t \n \r）
    ctrl_matches = _CONTROL_CHAR_RE.findall(text)
    if ctrl_matches:
        issues.append(AtsAuditIssue(
            section=section,
            issue_type=AtsIssueType.garbled,
            severity="medium",
            message=f"检测到 {len(ctrl_matches)} 个控制字符",
            suggestion="控制字符可能导致 ATS 解析异常，建议清除",
            context=None,
        ))

    return issues


def _scan_blank(text: str, section: str = "全文") -> list[AtsAuditIssue]:
    """扫描空白段落。

    检测：
    1. 空段落（strip 后长度为 0）
    2. 连续空行（3 行及以上空行）
    """
    issues: list[AtsAuditIssue] = []

    # 空段落
    paragraphs = [p.strip() for p in text.split("\n")]
    empty_count = sum(1 for p in paragraphs if not p)
    if empty_count > 3:
        issues.append(AtsAuditIssue(
            section=section,
            issue_type=AtsIssueType.blank,
            severity="low",
            message=f"检测到 {empty_count} 个空行/空段落",
            suggestion="过多空行会浪费 ATS 解析空间，建议精简格式",
            context=None,
        ))

    # 连续空行
    blank_runs = _CONSECUTIVE_BLANK_RE.findall(text)
    if blank_runs:
        issues.append(AtsAuditIssue(
            section=section,
            issue_type=AtsIssueType.blank,
            severity="medium",
            message=f"检测到 {len(blank_runs)} 处连续空行",
            suggestion="连续空行可能导致 ATS 将内容识别为空节段",
            context=None,
        ))

    return issues


def _scan_special_symbols(text: str, section: str = "全文") -> list[AtsAuditIssue]:
    """扫描特殊符号。

    检测：
    1. 装饰性符号（●◆★ 等）
    2. Emoji
    3. 大量竖线（表格布局滥用）
    """
    issues: list[AtsAuditIssue] = []

    # 装饰性符号
    sym_matches = _SPECIAL_SYMBOL_RE.findall(text)
    if sym_matches:
        issues.append(AtsAuditIssue(
            section=section,
            issue_type=AtsIssueType.special_symbol,
            severity="medium",
            message=f"检测到 {len(sym_matches)} 个装饰性符号（{''.join(list(set(sym_matches))[:5])}）",
            suggestion="部分 ATS 不支持特殊 Unicode 符号，建议替换为纯文本",
            context=None,
        ))

    # Emoji
    emoji_matches = _EMOJI_RE.findall(text)
    if emoji_matches:
        issues.append(AtsAuditIssue(
            section=section,
            issue_type=AtsIssueType.special_symbol,
            severity="medium",
            message=f"检测到 {len(emoji_matches)} 个 Emoji 字符",
            suggestion="Emoji 在 ATS 解析中可能显示为乱码或被忽略",
            context=None,
        ))

    # 大量竖线（表格布局滥用）
    pipe_count = text.count("|")
    # 排除 Markdown 表格（合理使用）和联系方式分隔
    # 只在竖线数量异常多时报警
    non_space_text_len = len(text.replace(" ", "").replace("\n", ""))
    if pipe_count > 10 and non_space_text_len > 0:
        pipe_ratio = pipe_count / non_space_text_len
        if pipe_ratio > 0.05:  # 竖线占比超过 5%
            issues.append(AtsAuditIssue(
                section=section,
                issue_type=AtsIssueType.special_symbol,
                severity="low",
                message=f"检测到大量竖线分隔符（{pipe_count} 个），疑似表格布局",
                suggestion="表格布局在 ATS 中可能无法正确解析，建议改用纯文本格式",
                context=None,
            ))

    return issues


def _scan_image_text(sections: list[dict[str, str]]) -> list[AtsAuditIssue]:
    """扫描图片中的文字（PDF 路径）。

    在 PDF 中，图片通常位于特定区域，如果图片区域附近无可提取文本，
    说明该区域的文字可能是图片形式，ATS 无法解析。
    """
    issues: list[AtsAuditIssue] = []

    for section_data in sections:
        section = section_data.get("section", "未知")
        # 如果一个节段完全没有文本内容，可能是图片/图表区域
        text = section_data.get("text", "").strip()
        if not text:
            # 只在有图片的区域报警（PDF 路径会提供 images 信息）
            pass  # 图片检测在 PDF 路径中通过 pdfplumber 实现

    return issues


def _scan_tables_from_text(text: str, section: str = "全文") -> list[AtsAuditIssue]:
    """从纯文本中检测表格布局。

    在 HTML 路径中，表格可能表现为 Markdown 表格或竖线分隔。
    在 PDF 路径中，表格通过 pdfplumber find_tables 检测。
    """
    issues: list[AtsAuditIssue] = []

    # Markdown 表格（| --- | --- |）
    md_table_re = re.compile(r"\|[-:\s]+\|[-:\s]+\|")
    md_tables = md_table_re.findall(text)
    if md_tables:
        issues.append(AtsAuditIssue(
            section=section,
            issue_type=AtsIssueType.table,
            severity="medium",
            message=f"检测到 {len(md_tables)} 个 Markdown 表格",
            suggestion="表格在 ATS 中可能无法正确解析，建议改用列表格式",
            context=None,
        ))

    return issues


def _scan_pdf_tables(
    pdf_tables: list, section: str = "全文"
) -> list[AtsAuditIssue]:
    """从 pdfplumber 检测到的表格中生成问题。

    Args:
        pdf_tables: pdfplumber page.find_tables() 返回的表格列表
        section: 节段名称
    """
    issues: list[AtsAuditIssue] = []

    for table in pdf_tables:
        try:
            table_data = table.extract()
            if table_data and len(table_data) > 1:
                rows = len(table_data)
                cols = len(table_data[0]) if table_data[0] else 0
                issues.append(AtsAuditIssue(
                    section=section,
                    issue_type=AtsIssueType.table,
                    severity="medium",
                    message=f"检测到表格区域（{rows} 行 x {cols} 列）",
                    suggestion="表格在 ATS 中可能无法正确解析，建议改用列表格式呈现关键信息",
                    context=None,
                ))
        except Exception:
            # 表格提取失败，跳过
            pass

    return issues


def _scan_pdf_images(
    pdf_images: list, text: str, section: str = "全文"
) -> list[AtsAuditIssue]:
    """从 pdfplumber 检测到的图片中生成问题。

    如果图片附近没有可提取的文本，说明该区域的文字可能是图片形式。
    """
    issues: list[AtsAuditIssue] = []

    if not pdf_images:
        return issues

    # 如果页面有图片但提取的文本很少（<50 字符），说明图片可能是主要内容
    text_len = len(text.strip())
    if text_len < 50 and pdf_images:
        issues.append(AtsAuditIssue(
            section=section,
            issue_type=AtsIssueType.image_text,
            severity="high",
            message=f"检测到 {len(pdf_images)} 个图片但可提取文本很少（{text_len} 字符）",
            suggestion="图片中的文字无法被 ATS 识别，请确保关键信息以文本形式呈现",
            context=None,
        ))
    elif pdf_images:
        issues.append(AtsAuditIssue(
            section=section,
            issue_type=AtsIssueType.image_text,
            severity="low",
            message=f"检测到 {len(pdf_images)} 个图片元素",
            suggestion="确认图片中不包含关键信息（如技能列表、工作描述），否则 ATS 无法识别",
            context=None,
        ))

    return issues


# ═══════════════════════════════════════════════════════════
# 评分函数
# ═══════════════════════════════════════════════════════════


def _score(issues: list[AtsAuditIssue]) -> int:
    """计算 ATS 可读性得分。

    公式：100 - 20*high - 10*medium - 4*low，clamp >= 0。
    """
    high = sum(1 for i in issues if i.severity == "high")
    medium = sum(1 for i in issues if i.severity == "medium")
    low = sum(1 for i in issues if i.severity == "low")
    raw = 100 - 20 * high - 10 * medium - 4 * low
    return max(0, raw)


# ═══════════════════════════════════════════════════════════
# HTML 审计路径
# ═══════════════════════════════════════════════════════════


def _audit_html(html: str) -> list[AtsAuditIssue]:
    """从 HTML 内容中扫描 ATS 问题。"""
    parser = _HtmlSectionParser()
    parser.feed(html)
    sections = parser.get_sections()

    all_issues: list[AtsAuditIssue] = []

    for section_data in sections:
        section_name = section_data["section"]
        text = section_data["text"]

        if not text.strip():
            all_issues.append(AtsAuditIssue(
                section=section_name,
                issue_type=AtsIssueType.blank,
                severity="medium",
                message="节段内容为空",
                suggestion="空节段会影响 ATS 关键词提取，请补充内容或删除该节段",
                context=None,
            ))
            continue

        all_issues.extend(_scan_garbled(text, section_name))
        all_issues.extend(_scan_blank(text, section_name))
        all_issues.extend(_scan_special_symbols(text, section_name))
        all_issues.extend(_scan_tables_from_text(text, section_name))

    # 全文扫描：仅检测连续空行（跨节段上下文，per-section 扫描无法捕获）
    full_text = "\n".join(s["text"] for s in sections)
    all_issues.extend(_scan_blank(full_text, "全文"))

    return _dedup_issues(all_issues)


# ═══════════════════════════════════════════════════════════
# PDF 审计路径
# ═══════════════════════════════════════════════════════════


def _audit_pdf(pdf_bytes: bytes) -> list[AtsAuditIssue]:
    """从 PDF 字节流中扫描 ATS 问题。"""
    all_issues: list[AtsAuditIssue] = []

    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber not available, skipping PDF audit")
        return []

    try:
        pdf_file = io.BytesIO(pdf_bytes)
        with pdfplumber.open(pdf_file) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                page_label = f"第 {page_idx + 1} 页"

                # 提取文本
                text = page.extract_text() or ""

                # 检测表格
                try:
                    tables = page.find_tables()
                    all_issues.extend(_scan_pdf_tables(tables, page_label))
                except Exception:
                    pass

                # 检测图片
                try:
                    images = page.images or []
                    all_issues.extend(_scan_pdf_images(images, text, page_label))
                except Exception:
                    pass

                # 文本扫描
                if text.strip():
                    all_issues.extend(_scan_garbled(text, page_label))
                    all_issues.extend(_scan_blank(text, page_label))
                    all_issues.extend(_scan_special_symbols(text, page_label))
                    all_issues.extend(_scan_tables_from_text(text, page_label))

    except Exception as e:
        logger.warning("PDF audit failed: %s", e)

    return _dedup_issues(all_issues)


# ═══════════════════════════════════════════════════════════
# 去重
# ═══════════════════════════════════════════════════════════


def _dedup_issues(issues: list[AtsAuditIssue]) -> list[AtsAuditIssue]:
    """按 (section, issue_type, message) 去重。"""
    seen: set[tuple[str, str, str]] = set()
    deduped: list[AtsAuditIssue] = []
    for issue in issues:
        key = (issue.section, issue.issue_type.value, issue.message)
        if key not in seen:
            seen.add(key)
            deduped.append(issue)
    return deduped


# ═══════════════════════════════════════════════════════════
# 编排入口
# ═══════════════════════════════════════════════════════════


async def audit_resume(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> AtsAuditResponse:
    """执行 ATS 可读性审计。

    双路径：
    1. HTML 直读（始终执行）：render_resume → _HtmlSectionParser
    2. PDF 回读（WeasyPrint 可用时追加）：export_resume_pdf → pdfplumber

    两路结果按 section+type 合并去重，method 字段如实上报。

    Raises:
        HTTPException 404: 简历不存在或非本人
        HTTPException 409: 简历未就绪
        HTTPException 422: 零模块
    """
    from services.resume_builder import get_resume_with_modules
    from services.resume_template import render_resume
    from schemas.resume_module import ResumeStyle

    resume, modules = await get_resume_with_modules(db, user_id, resume_id)

    # 状态校验
    if resume.status not in ("ready", "draft"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"简历未就绪（当前状态: {resume.status}），无法执行 ATS 审计",
        )

    # 零模块守卫
    if not modules:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="简历没有任何模块内容，无法执行 ATS 审计。请先添加模块。",
        )

    # 解析 style
    style = ResumeStyle.from_db(resume.style)

    warnings: list[str] = []
    html_issues: list[AtsAuditIssue] = []
    pdf_issues: list[AtsAuditIssue] = []
    method = "html"

    # ── 路径 1：HTML 直读（始终执行） ──
    try:
        html_str = render_resume(modules, style, resume.filename)
        html_issues = _audit_html(html_str)
    except Exception as e:
        logger.warning("HTML audit failed: %s", e)
        warnings.append(f"HTML 审计失败: {e}")

    # ── 路径 2：PDF 回读（WeasyPrint 可用时追加） ──
    pdf_available = False
    try:
        from services.resume_export import _get_weasyprint, _resolve_upload_urls

        HTML = _get_weasyprint()
        if HTML is not None:
            html_for_pdf = render_resume(modules, style, resume.filename)
            html_for_pdf = _resolve_upload_urls(html_for_pdf)

            pdf_buffer = io.BytesIO()
            HTML(string=html_for_pdf).write_pdf(pdf_buffer)
            pdf_bytes = pdf_buffer.getvalue()

            pdf_issues = _audit_pdf(pdf_bytes)
            pdf_available = True
        else:
            warnings.append("WeasyPrint 不可用（GTK 未安装），仅使用 HTML 路径审计")
    except HTTPException:
        # WeasyPrint 抛出的 HTTPException（如 503）→ 降级
        warnings.append("PDF 生成失败，仅使用 HTML 路径审计")
    except Exception as e:
        logger.warning("PDF audit path failed: %s", e)
        warnings.append(f"PDF 审计路径失败: {e}，仅使用 HTML 路径审计")

    # ── 合并结果 ──
    if pdf_available and pdf_issues:
        method = "pdf+html"
        all_issues = _dedup_issues(html_issues + pdf_issues)
    elif pdf_available:
        method = "pdf"
        all_issues = html_issues
    else:
        method = "html"
        all_issues = html_issues

    # 按 severity 排序（high → medium → low）
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_issues.sort(key=lambda i: severity_order.get(i.severity, 3))

    ats_score = _score(all_issues)

    logger.info(
        "ATS audit completed: resume=%d, score=%d, issues=%d, method=%s",
        resume_id, ats_score, len(all_issues), method,
    )

    return AtsAuditResponse(
        resume_id=resume_id,
        ats_score=ats_score,
        issue_count=len(all_issues),
        issues=all_issues,
        method=method,
        pdf_available=pdf_available,
        warnings=warnings,
    )
