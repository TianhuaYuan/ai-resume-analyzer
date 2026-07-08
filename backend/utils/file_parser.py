import logging
from collections.abc import Callable
from pathlib import Path

from docx import Document
from pypdf import PdfReader

logger = logging.getLogger(__name__)

MIN_SCAN_TEXT_LENGTH = 50


def parse_pdf(path: str) -> str:
    """逐页提取 PDF 文本"""
    reader = PdfReader(path)
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def parse_docx(path: str) -> str:
    """逐段提取 Word 文本"""
    doc = Document(path)
    return "\n".join((p.text or "") for p in doc.paragraphs).strip()


def parse_txt(path: str) -> str:
    """读取纯文本，UTF-8 → GBK 兜底"""
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
    ".docx": parse_docx,
    ".txt": parse_txt,
}


def parse_resume(path: str) -> str:
    """根据扩展名自动选 PDF/Word/TXT 解析器"""
    ext = Path(path).suffix.lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise ValueError(f"不支持的文件格式：{ext}")

    text = parser(path)
    if len(text) < MIN_SCAN_TEXT_LENGTH:
        logger.warning("解析文本过短: path=%s, len=%d", path, len(text))
        raise ValueError("解析文本过短，可能是扫描件 PDF")

    return text
