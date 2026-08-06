"""PDF 类型检测：文本型 vs 扫描件。

Phase 2.5 / P2：在 OCR 兜底前加一层门控——判定 PDF 是否有可提取的文字层
（文本型），还是图片转出的扫描件（扫描仪/截图/打印导出）。判定 = Producer
指纹 + 文本密度阈值，返回 (is_scanned, reason)。

Producer 指纹思路参考 third_party/SmartResume smartresume/data/pdf_checker.py：
- 文本型指纹（iText/Word/WPS 等生成型工具）→ 即使文本层意外偏少也判文本型
- 扫描件指纹（FFmpeg/ScanSoft 等图片转 PDF 工具）→ 直接判扫描件
- 无指纹 → 看平均每页可提取字符数（文本密度）

检测失败（PDF 损坏 / 无法打开）→ detected=False，调用方按既有长度逻辑兜底，
不影响正常文本 PDF 的解析行为。
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

# 扫描/图片转 PDF 工具常见 Producer 指纹（命中 → 高度怀疑扫描件）
_SCAN_PRODUCER_FINGERPRINTS = (
    "lavc", "lavf",        # FFmpeg（扫描仪/视频帧导出 PDF）
    "scansoft",            # 富士通 ScanSnap 等扫描仪
    "irfanview",           # 图片查看器转 PDF
    "adobe photoshop",     # 图片直接导出 PDF
    "ghostscript",         # 常见于图片合并转 PDF
    "nuance pdf",          # 扫描软件
    "canon",               # 佳能扫描/打印
    "epson",               # 爱普生扫描/打印
    "hp scan",             # 惠普扫描
    "hp photosmart",       # 惠普照片打印转 PDF
)

# 生成型（非扫描）Producer 指纹 → 判文本型
_TEXT_PRODUCER_FINGERPRINTS = (
    "itext", "agpl",                    # iText 生成 → 文本型
    "microsoft word", "microsoft® word",
    "libreoffice", "openoffice",
    "wps", "kingsoft",
    "pandoc", "latex", "tex",
    "pdfsharp", "reportlab", "weasyprint",
)

# 文本密度阈值（对齐 file_parser.MIN_SCAN_TEXT_LENGTH=50 语义，按页缩放）
SCAN_TEXT_TOTAL_MIN = 50      # 整篇最少字符数
SCAN_TEXT_DENSITY_PER_PAGE = 30  # 平均每页最少字符数
MAX_CHECK_PAGES = 5           # 内部自提文本时只读前 5 页，避免超长 PDF 全量读


@dataclass
class PdfTypeVerdict:
    """PDF 类型判定结果。

    Attributes:
        is_scanned: True=扫描件，False=文本型
        reason: 判定理由
        detected: False=检测失败（PDF 损坏/无法打开），调用方按既有逻辑兜底
        text_chars: 可提取文本字符数（0 = 未统计）
        page_count: PDF 页数
        producer: Producer 元数据原始值
        avg_chars_per_page: 平均每页字符数
    """

    is_scanned: bool
    reason: str
    detected: bool = True
    text_chars: int = 0
    page_count: int = 0
    producer: str = ""
    avg_chars_per_page: float = 0.0


def _read_metadata(path: str) -> tuple[str, int]:
    """读取 Producer 元数据与页数；失败返回 ("", 0)。"""
    if pdfplumber is None:
        return "", 0
    try:
        with pdfplumber.open(path) as pdf:
            page_count = len(pdf.pages)
            metadata = getattr(pdf, "metadata", None) or {}
            producer = metadata.get("Producer") or metadata.get("/Producer") or ""
            if isinstance(producer, bytes):
                producer = producer.decode("utf-8", errors="ignore")
            return str(producer or "").strip(), page_count
    except Exception as e:
        logger.warning("PDF 元数据读取失败: %s: %s", path, e)
        return "", 0


def _count_extractable_chars(path: str) -> int:
    """提取前 MAX_CHECK_PAGES 页的字符数，用于文本密度判定。"""
    if pdfplumber is None:
        return 0
    total = 0
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:MAX_CHECK_PAGES]:
                text = page.extract_text()
                if text:
                    total += len(text)
    except Exception as e:
        logger.warning("PDF 文本提取（密度统计）失败: %s: %s", path, e)
        return 0
    return total


def check_pdf_type(path: str, extracted_text: str | None = None) -> PdfTypeVerdict:
    """检测 PDF 为文本型还是扫描件。

    Args:
        path: PDF 文件路径
        extracted_text: 可选。调用方已提取的文本，复用避免二次提取（该文本是
            整篇提取结果）；None 时内部只统计前 MAX_CHECK_PAGES 页做密度判定。

    Returns:
        PdfTypeVerdict。检测失败（打不开）时 detected=False、is_scanned=False，
        调用方应回退到既有"文本过短 → OCR"逻辑。
    """
    if pdfplumber is None:
        return PdfTypeVerdict(
            is_scanned=False, reason="pdfplumber 不可用，跳过类型检测", detected=False
        )

    producer, page_count = _read_metadata(path)
    if page_count <= 0:
        # metadata 读取失败 / 空页数 → 无法判定，走兜底
        return PdfTypeVerdict(
            is_scanned=False, reason="无法读取 PDF（损坏或不可解析）", detected=False
        )

    producer_lower = producer.lower()

    # 1. Producer 指纹优先（文本型 > 扫描件，覆盖极端密度情况）
    if any(fp in producer_lower for fp in _TEXT_PRODUCER_FINGERPRINTS):
        return PdfTypeVerdict(
            is_scanned=False,
            reason=f"Producer 命中文本型指纹（{producer[:80]}）",
            page_count=page_count,
            producer=producer,
        )
    if any(fp in producer_lower for fp in _SCAN_PRODUCER_FINGERPRINTS):
        return PdfTypeVerdict(
            is_scanned=True,
            reason=f"Producer 命中扫描件指纹（{producer[:80]}）",
            page_count=page_count,
            producer=producer,
        )

    # 2. 文本密度判定（无指纹时）
    if extracted_text is not None:
        total_chars = len(extracted_text)
    else:
        total_chars = _count_extractable_chars(path)
    avg = total_chars / page_count

    if total_chars < SCAN_TEXT_TOTAL_MIN or avg < SCAN_TEXT_DENSITY_PER_PAGE:
        return PdfTypeVerdict(
            is_scanned=True,
            reason=(
                f"文本密度过低（共 {total_chars} 字符 / {page_count} 页，"
                f"平均 {avg:.1f} 字符/页）"
            ),
            text_chars=total_chars,
            page_count=page_count,
            producer=producer,
            avg_chars_per_page=avg,
        )

    return PdfTypeVerdict(
        is_scanned=False,
        reason=(
            f"文本层充足（共 {total_chars} 字符 / {page_count} 页，"
            f"平均 {avg:.1f} 字符/页）"
        ),
        text_chars=total_chars,
        page_count=page_count,
        producer=producer,
        avg_chars_per_page=avg,
    )
