from pathlib import Path

from docx import Document
from pypdf import PdfReader


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
    return "\n".join(p.text for p in doc.paragraphs).strip()


def parse_resume(path: str) -> str:
    """根据扩展名自动选 PDF/Word 解析器"""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        text = parse_pdf(path)
    elif ext == ".docx":
        text = parse_docx(path)
    else:
        raise ValueError(f"不支持的文件格式：{ext}")

    if len(text) < MIN_SCAN_TEXT_LENGTH:
        raise ValueError("解析文本过短，可能是扫描件 PDF")

    return text
