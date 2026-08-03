import logging
import re
from collections.abc import Callable
from pathlib import Path

import pdfplumber
from docx import Document

logger = logging.getLogger(__name__)

# 延迟导入 MinerU 客户端，避免在 import 阶段强依赖网络配置
_mineru_client = None


def _get_mineru_client():
    global _mineru_client
    if _mineru_client is None:
        from services.mineru_parser import get_mineru_client

        _mineru_client = get_mineru_client()
    return _mineru_client

MIN_SCAN_TEXT_LENGTH = 50

# 常见简历节标题（用于分节标注）
_SECTION_HEADERS = {
    "个人信息", "基本信息", "个人资料",
    "教育背景", "教育经历", "学历",
    "工作经验", "工作经历", "实习经历", "实习经验",
    "项目经历", "项目经验", "项目",
    "专业技能", "技能", "技术栈",
    "自我评价", "个人评价", "总结",
    "荣誉奖项", "获奖情况", "证书",
    "语言能力", "语言",
    "兴趣爱好", "特长",
    "求职意向", "意向岗位",
}

# 预编译正则：行首匹配节标题（整行完全一致，忽略空白）
_SECTION_RE = re.compile(
    r"^[\s]*(" + "|".join(re.escape(h) for h in _SECTION_HEADERS) + r")[\s]*$",
    re.MULTILINE,
)


def _annotate_sections(text: str) -> str:
    """对文本中的节标题前加 `## ` 标注。

    已标注的行不会重复添加。
    """

    def _replace(match: re.Match) -> str:
        line = match.group(0)
        # 如果已经以 ## 开头，不重复添加
        stripped = line.strip()
        if stripped.startswith("## "):
            return line
        return line.replace(stripped, f"## {stripped}", 1)

    return _SECTION_RE.sub(_replace, text)


def parse_pdf(path: str) -> str:
    """用 pdfplumber 逐页提取 PDF 文本。"""
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def parse_docx(path: str) -> str:
    """逐段 + 逐表格提取 Word 文本。"""
    doc = Document(path)
    parts = []

    # 1. 普通段落
    for p in doc.paragraphs:
        if p.text:
            parts.append(p.text)

    # 2. 表格（逐行逐单元格拼接）
    for table in doc.tables:
        for row in table.rows:
            row_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if row_texts:
                parts.append(" | ".join(row_texts))

    return "\n".join(parts).strip()


def parse_docx_with_sections(path: str) -> str:
    """提取 DOCX 文本并标注节标题。"""
    text = parse_docx(path)
    return _annotate_sections(text)


def parse_txt(path: str) -> str:
    """读取纯文本，UTF-8 → GBK 兜底。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "gbk", "gb2312"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


_PARSERS: dict[str, Callable[[str], str]] = {
    ".pdf": parse_pdf,
    ".docx": parse_docx_with_sections,
}


async def parse_resume(path: str) -> str:
    """根据扩展名自动选解析器。优先 MinerU，失败 fallback 本地解析。"""
    ext = Path(path).suffix.lower()

    # 1. 优先尝试 MinerU 精准解析（PDF/DOCX）
    if ext in {".pdf", ".docx"}:
        try:
            client = _get_mineru_client()
            mineru_text = await client.parse_file(path)
            if mineru_text and len(mineru_text) >= MIN_SCAN_TEXT_LENGTH:
                logger.info("MinerU 解析成功: path=%s, len=%d", path, len(mineru_text))
                # MinerU 输出已是 markdown，对 PDF 也做分节标注增强
                if ext == ".pdf":
                    mineru_text = _annotate_sections(mineru_text)
                return mineru_text
        except Exception as e:
            logger.warning("MinerU 解析失败，fallback 本地解析: %s", e)

    # 2. Fallback 本地解析
    parser = _PARSERS.get(ext)
    if parser is None:
        if ext == ".txt":
            text = parse_txt(path)
        else:
            raise ValueError(f"不支持的文件格式：{ext}")
    else:
        text = parser(path)

    # PDF 也做分节标注（DOCX 在 parse_docx_with_sections 里已做）
    if ext == ".pdf":
        text = _annotate_sections(text)

    if len(text) < MIN_SCAN_TEXT_LENGTH:
        logger.warning("解析文本过短: path=%s, len=%d", path, len(text))
        raise ValueError("解析文本过短，可能是扫描件 PDF")

    return text
