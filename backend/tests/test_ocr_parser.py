"""A2: 扫描件 OCR 兜底测试。

覆盖：
- ocr_pdf：成功拼接逐页文本 / 未安装依赖返回 None / 异常返回 None / 空结果返回 None
- parse_resume：文本过短的 PDF 走 OCR 兜底成功 / OCR 也失败维持 ValueError / 正常文本不触发 OCR
"""

import pytest
from unittest.mock import AsyncMock, patch

from utils.file_parser import MIN_SCAN_TEXT_LENGTH, parse_resume
from utils.ocr_parser import ocr_pdf


class _FakePage:
    """模拟 pdfplumber 页面（extract_text + to_image().original）。"""

    def __init__(self, text: str = "短文本"):
        self._text = text

    def extract_text(self):
        return self._text

    def to_image(self, resolution: int):
        return self

    @property
    def original(self):
        return "PIL-IMAGE"


class _FakePDF:
    """模拟 pdfplumber.open 的上下文管理器。"""

    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_engine(img):
    """模拟 RapidOCR 引擎：返回 ([[box, text, score], ...], elapse)。"""
    return [
        ([[0, 0, 10, 10]], "张三", 0.95),
        ([[0, 0, 10, 10]], "Python工程师", 0.9),
        ([[0, 0, 10, 10]], "", 0.5),  # 空文本应被过滤
    ], 0.1


# ═══════════════════════════════════════════════════════════
# ocr_pdf
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ocr_pdf_concatenates_pages():
    """OCR 成功：逐页识别文本拼接，空文本过滤。"""
    with patch("pdfplumber.open", return_value=_FakePDF([_FakePage(), _FakePage()])), \
         patch("utils.ocr_parser._get_ocr_engine", return_value=_fake_engine):
        text = await ocr_pdf("/tmp/scan.pdf")

    assert text == "张三\nPython工程师\n张三\nPython工程师"


@pytest.mark.asyncio
async def test_ocr_pdf_missing_dependency_returns_none():
    """RapidOCR 未安装 → 返回 None（优雅降级，不抛异常）。"""
    with patch("pdfplumber.open", return_value=_FakePDF([_FakePage()])), \
         patch("utils.ocr_parser._get_ocr_engine", side_effect=ImportError("no rapidocr")):
        text = await ocr_pdf("/tmp/scan.pdf")

    assert text is None


@pytest.mark.asyncio
async def test_ocr_pdf_exception_returns_none():
    """OCR 引擎异常 → 返回 None（不影响主流程）。"""
    with patch("pdfplumber.open", return_value=_FakePDF([_FakePage()])), \
         patch("utils.ocr_parser._get_ocr_engine", side_effect=RuntimeError("model download failed")):
        text = await ocr_pdf("/tmp/scan.pdf")

    assert text is None


@pytest.mark.asyncio
async def test_ocr_pdf_empty_result_returns_none():
    """OCR 全页无有效文本 → 返回 None。"""
    with patch("pdfplumber.open", return_value=_FakePDF([_FakePage()])), \
         patch("utils.ocr_parser._get_ocr_engine", return_value=([], 0.1)):
        text = await ocr_pdf("/tmp/scan.pdf")

    assert text is None


# ═══════════════════════════════════════════════════════════
# parse_resume 扫描件兜底链路
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_parse_resume_short_text_falls_back_to_ocr():
    """PDF 本地解析文本过短（疑似扫描件）→ OCR 兜底成功返回识别文本。"""
    with patch("pdfplumber.open", return_value=_FakePDF([_FakePage("短文本")])), \
         patch("utils.ocr_parser.ocr_pdf", new_callable=AsyncMock,
               return_value="张三\nPython工程师\n3年经验\n" * 10) as mock_ocr:
        text = await parse_resume("/tmp/scan.pdf")

    mock_ocr.assert_awaited_once()
    assert "张三" in text
    assert len(text) >= MIN_SCAN_TEXT_LENGTH


@pytest.mark.asyncio
async def test_parse_resume_ocr_failure_keeps_valueerror():
    """OCR 也失败 → 维持原 ValueError 行为。"""
    with patch("pdfplumber.open", return_value=_FakePDF([_FakePage("短文本")])), \
         patch("utils.ocr_parser.ocr_pdf", new_callable=AsyncMock, return_value=None):
        with pytest.raises(ValueError, match="扫描件"):
            await parse_resume("/tmp/scan.pdf")


@pytest.mark.asyncio
async def test_parse_resume_normal_text_skips_ocr():
    """正常 PDF 文本足够 → 不触发 OCR。"""
    with patch("pdfplumber.open", return_value=_FakePDF([_FakePage("张三\nPython 工程师\n" * 30)])), \
         patch("utils.ocr_parser.ocr_pdf", new_callable=AsyncMock) as mock_ocr:
        text = await parse_resume("/tmp/normal.pdf")

    assert "Python" in text
    mock_ocr.assert_not_awaited()
