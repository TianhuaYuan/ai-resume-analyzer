"""T5: file_parser 增强 — pdfplumber + docx 表格 + 分节标注。

测试范围：
- parse_pdf 用 pdfplumber 提取文本
- parse_docx 提取段落 + 表格内容
- parse_resume 对节标题加 `## 节名` 标注
"""

from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════
# RED: parse_pdf 用 pdfplumber
# ═══════════════════════════════════════════════════════════


class TestParsePdfPdfplumber:
    """PDF 解析应使用 pdfplumber 提取文本。"""

    @patch("utils.file_parser.pdfplumber")
    def test_extracts_text_from_pages(self, mock_pdfplumber):
        """逐页提取并拼接文本。"""
        from utils.file_parser import parse_pdf

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page one content"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page two content"

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber.open.return_value = mock_pdf

        result = parse_pdf("/fake/resume.pdf")
        assert result == "Page one content\nPage two content"

    @patch("utils.file_parser.pdfplumber")
    def test_handles_empty_pages(self, mock_pdfplumber):
        """空页面应被跳过，不残留 None。"""
        from utils.file_parser import parse_pdf

        mock_page = MagicMock()
        mock_page.extract_text.return_value = None

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber.open.return_value = mock_pdf

        result = parse_pdf("/fake/empty.pdf")
        assert result == ""

    @patch("utils.file_parser.pdfplumber")
    def test_strips_whitespace(self, mock_pdfplumber):
        """结果应 strip 前后空白。"""
        from utils.file_parser import parse_pdf

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "  content  "

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber.open.return_value = mock_pdf

        result = parse_pdf("/fake/resume.pdf")
        assert result == "content"


def test_extract_link_evidence_keeps_labelled_pdf_uri():
    """可点击 GitHub 注释必须进入文本证据，不能只留下“主页链接”标签。"""
    from utils.file_parser import _extract_link_evidence

    links = [
        {
            "uri": "https://github.com/candidate",
            "x0": 10,
            "x1": 90,
            "top": 20,
            "bottom": 40,
        }
    ]
    words = [
        {"text": "GitHub主页链接", "x0": 12, "x1": 88, "top": 22, "bottom": 38}
    ]

    assert _extract_link_evidence(links, words, "GitHub主页链接") == [
        "GitHub主页链接: https://github.com/candidate"
    ]


def test_extract_link_evidence_deduplicates_visible_and_rejects_unsafe_scheme():
    from utils.file_parser import _extract_link_evidence

    links = [
        {"uri": "https://example.com", "x0": 0, "x1": 1, "top": 0, "bottom": 1},
        {"uri": "javascript:alert(1)", "x0": 0, "x1": 1, "top": 0, "bottom": 1},
    ]

    assert _extract_link_evidence(links, [], "项目：https://example.com") == []


# ═══════════════════════════════════════════════════════════
# RED: parse_docx 表格 + 段落
# ═══════════════════════════════════════════════════════════


class TestParseDocxTables:
    """DOCX 解析应提取段落和表格内容。"""

    @patch("utils.file_parser.Document")
    def test_extracts_paragraphs_and_tables(self, mock_Document):
        """段落和表格行都应被提取。"""
        from utils.file_parser import parse_docx

        mock_doc = MagicMock()
        mock_para1 = MagicMock()
        mock_para1.text = "Paragraph one"
        mock_para2 = MagicMock()
        mock_para2.text = "Paragraph two"
        mock_doc.paragraphs = [mock_para1, mock_para2]

        # 模拟一个 2x2 表格
        mock_cell_a = MagicMock()
        mock_cell_a.text = "Cell A"
        mock_cell_b = MagicMock()
        mock_cell_b.text = "Cell B"
        mock_row = MagicMock()
        mock_row.cells = [mock_cell_a, mock_cell_b]
        mock_table = MagicMock()
        mock_table.rows = [mock_row]
        mock_doc.tables = [mock_table]

        mock_Document.return_value = mock_doc

        result = parse_docx("/fake/resume.docx")
        assert "Paragraph one" in result
        assert "Paragraph two" in result
        assert "Cell A" in result
        assert "Cell B" in result

    @patch("utils.file_parser.Document")
    def test_empty_doc_returns_empty(self, mock_Document):
        """空文档返回空字符串。"""
        from utils.file_parser import parse_docx

        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        mock_doc.tables = []
        mock_Document.return_value = mock_doc

        result = parse_docx("/fake/empty.docx")
        assert result == ""


# ═══════════════════════════════════════════════════════════
# RED: 分节标注
# ═══════════════════════════════════════════════════════════


class TestSectionHeadersAnnotation:
    """parse_resume 应对常见节标题加 `## 节名` 标注。"""

    @pytest.mark.asyncio
    @patch("utils.file_parser._get_mineru_client")
    @patch("utils.file_parser.pdfplumber")
    async def test_annotates_section_headers_in_pdf(self, mock_pdfplumber, mock_mineru):
        """PDF 文本中的节标题应被标注。"""
        from utils.file_parser import parse_resume

        mock_mineru.return_value.enabled = False

        raw_text = "张三\n教育背景\n北京大学 计算机科学\n工作经验\n字节跳动 后端开发\n" + "a" * 50

        mock_page = MagicMock()
        mock_page.extract_text.return_value = raw_text
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        result = await parse_resume("/fake/resume.pdf")
        assert "## 教育背景" in result
        assert "## 工作经验" in result

    @patch("utils.file_parser.Document")
    def test_annotates_section_headers_in_docx(self, mock_Document):
        """DOCX 文本中的节标题应被标注。"""
        from utils.file_parser import parse_docx_with_sections

        raw_text = "李四\n专业技能\nPython Java\n项目经历\nAI 简历分析系统"

        mock_para = MagicMock()
        mock_para.text = raw_text
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]
        mock_doc.tables = []
        mock_Document.return_value = mock_doc

        result = parse_docx_with_sections("/fake/resume.docx")
        assert "## 专业技能" in result
        assert "## 项目经历" in result

    @pytest.mark.asyncio
    @patch("utils.file_parser._get_mineru_client")
    @patch("utils.file_parser.pdfplumber")
    async def test_does_not_duplicate_annotations(self, mock_pdfplumber, mock_mineru):
        """已标注的节标题不应重复加 `##`。"""
        from utils.file_parser import parse_resume

        mock_mineru.return_value.enabled = False

        raw_text = "王五\n## 教育背景\n清华大学\n" + "a" * 50

        mock_page = MagicMock()
        mock_page.extract_text.return_value = raw_text
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        result = await parse_resume("/fake/resume.pdf")
        # 不应出现 "## ## 教育背景"
        assert result.count("## 教育背景") == 1

    def test_annotate_sections_standalone(self):
        """_annotate_sections 独立测试：匹配常见节标题。"""
        from utils.file_parser import _annotate_sections

        text = "个人信息\n姓名：张三\n工作经验\n公司A\n教育背景\n大学B"
        result = _annotate_sections(text)
        assert "## 个人信息" in result
        assert "## 工作经验" in result
        assert "## 教育背景" in result

    def test_annotate_sections_skips_non_headers(self):
        """非节标题行不应被标注。"""
        from utils.file_parser import _annotate_sections

        text = "Hello world\nThis is not a section\nPython developer"
        result = _annotate_sections(text)
        assert "## Hello world" not in result
        assert "## This is not a section" not in result


# ═══════════════════════════════════════════════════════════
# RED: 集成 — parse_resume 仍保持最小长度检查
# ═══════════════════════════════════════════════════════════


class TestParseResumeIntegration:
    """parse_resume 集成行为保持不变。"""

    @pytest.mark.asyncio
    @patch("utils.file_parser._get_mineru_client")
    @patch("utils.file_parser.pdfplumber")
    async def test_rejects_too_short_text(self, mock_pdfplumber, mock_mineru):
        """文本过短仍抛 ValueError。"""
        from utils.file_parser import parse_resume

        mock_mineru.return_value.enabled = False

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "hi"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        with pytest.raises(ValueError, match="解析文本过短"):
            await parse_resume("/fake/short.pdf")

    @pytest.mark.asyncio
    @patch("utils.file_parser._get_mineru_client")
    @patch("utils.file_parser.pdfplumber")
    async def test_accepts_pdf_extension(self, mock_pdfplumber, mock_mineru):
        """.pdf 扩展名正常解析。"""
        from utils.file_parser import parse_resume

        mock_mineru.return_value.enabled = False

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "a" * 100
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        result = await parse_resume("/fake/resume.PDF")
        assert len(result) >= 50
