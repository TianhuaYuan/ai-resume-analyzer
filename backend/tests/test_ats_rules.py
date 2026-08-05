"""
ATS 审计规则纯函数测试（P0-A）。

覆盖：乱码检测 / 空白段检测 / 特殊符号检测 / 表格检测 / 评分函数。
"""

import pytest

from schemas.resume import AtsIssueType
from services.ats_audit_service import (
    _is_garbled,
    _scan_blank,
    _scan_garbled,
    _scan_special_symbols,
    _scan_tables_from_text,
    _score,
    _dedup_issues,
    _audit_html,
    _HtmlSectionParser,
)


# ═══════════════════════════════════════════════════════════
# _is_garbled 单元测试
# ═══════════════════════════════════════════════════════════


class TestIsGarbled:
    def test_short_string_not_garbled(self):
        """短字符串不判定为乱码。"""
        assert _is_garbled("hello") is False

    def test_string_with_spaces_not_garbled(self):
        """含空格的字符串不判定为乱码。"""
        assert _is_garbled("hello world " + "x" * 40) is False
        assert _is_garbled("Senior Software Engineer with expertise in Python") is False

    def test_string_with_chinese_not_garbled(self):
        """含中文的字符串不判定为乱码。"""
        assert _is_garbled("这是中文测试" + "a" * 40) is False

    def test_long_pure_ascii_may_be_garbled(self):
        """长纯 ASCII 无空格串可能判定为乱码。"""
        # 长度 > 40，无空格，无中文 → 可能是乱码
        garbled = "abcdefghijklmnopqrstuvwxyz0123456789" * 2
        assert _is_garbled(garbled) is True

    def test_normal_english_text_not_garbled(self):
        """正常英文文本不判定为乱码。"""
        text = "Senior Software Engineer with expertise in Python and FastAPI"
        assert _is_garbled(text) is False


# ═══════════════════════════════════════════════════════════
# _scan_garbled 测试
# ═══════════════════════════════════════════════════════════


class TestScanGarbled:
    def test_normal_text_no_issues(self):
        """正常文本无乱码问题。"""
        text = "Python 后端工程师，3年 FastAPI 开发经验。负责核心接口设计与优化。"
        issues = _scan_garbled(text, "工作经历")
        assert len(issues) == 0

    def test_replacement_char_detected(self):
        """检测到 Unicode 替换字符。"""
        text = "工作经历：�Python 开发"
        issues = _scan_garbled(text, "工作经历")
        assert len(issues) >= 1
        assert any(i.issue_type == AtsIssueType.garbled for i in issues)
        assert any(i.severity == "high" for i in issues)

    def test_control_chars_detected(self):
        """检测到控制字符。"""
        text = "工作经历：Python\x00\x01开发"
        issues = _scan_garbled(text, "工作经历")
        assert any(i.issue_type == AtsIssueType.garbled for i in issues)
        assert any("控制字符" in i.message for i in issues)

    def test_garbled_long_ascii_detected(self):
        """检测到长 ASCII 乱码串。"""
        garbled = "abcdefghijklmnopqrstuvwxyz0123456789" * 2
        text = f"正常文本 {garbled} 正常文本"
        issues = _scan_garbled(text, "技能")
        garbled_issues = [i for i in issues if i.issue_type == AtsIssueType.garbled]
        assert len(garbled_issues) >= 1

    def test_chinese_url_not_false_positive(self):
        """中文 + URL 不应被误判为乱码。"""
        text = "个人主页：https://github.com/username/portfolio 和博客地址"
        issues = _scan_garbled(text, "社交链接")
        # URL 中的长字母串不应被误判
        garbled_issues = [
            i for i in issues
            if i.issue_type == AtsIssueType.garbled and "乱码" in i.message
        ]
        assert len(garbled_issues) == 0


# ═══════════════════════════════════════════════════════════
# _scan_blank 测试
# ═══════════════════════════════════════════════════════════


class TestScanBlank:
    def test_normal_text_no_issues(self):
        """正常文本无空白问题。"""
        text = "工作经历\n负责核心接口设计\n优化系统性能"
        issues = _scan_blank(text, "工作经历")
        assert len(issues) == 0

    def test_many_empty_lines_detected(self):
        """检测到过多空行。"""
        text = "工作经历\n\n\n\n\n\n\n\n\n\n\n"
        issues = _scan_blank(text, "工作经历")
        assert len(issues) >= 1
        assert any(i.issue_type == AtsIssueType.blank for i in issues)

    def test_consecutive_blank_lines_detected(self):
        """检测到连续空行。"""
        text = "第一行\n\n\n\n第二行"
        issues = _scan_blank(text, "工作经历")
        assert any("连续空行" in i.message for i in issues)


# ═══════════════════════════════════════════════════════════
# _scan_special_symbols 测试
# ═══════════════════════════════════════════════════════════


class TestScanSpecialSymbols:
    def test_normal_text_no_issues(self):
        """正常文本无特殊符号问题。"""
        text = "工作经历：负责核心接口设计，优化系统性能。"
        issues = _scan_special_symbols(text, "工作经历")
        assert len(issues) == 0

    def test_decorative_symbols_detected(self):
        """检测到装饰性符号。"""
        text = "● 工作经历\n◆ 技能\n★ 荣誉"
        issues = _scan_special_symbols(text, "全文")
        assert any(i.issue_type == AtsIssueType.special_symbol for i in issues)

    def test_emoji_detected(self):
        """检测到 Emoji。"""
        text = "工作经历 🎯 负责核心接口设计 🚀"
        issues = _scan_special_symbols(text, "工作经历")
        assert any(i.issue_type == AtsIssueType.special_symbol for i in issues)

    def test_excessive_pipes_detected(self):
        """检测到大量竖线分隔符。"""
        text = "a|b|c|d|e|f|g|h|i|j|k|l|m|n|o|p|q|r|s|t|u|v|w|x|y|z|1|2|3"
        issues = _scan_special_symbols(text, "技能")
        pipe_issues = [i for i in issues if "竖线" in i.message]
        assert len(pipe_issues) >= 1


# ═══════════════════════════════════════════════════════════
# _scan_tables_from_text 测试
# ═══════════════════════════════════════════════════════════


class TestScanTables:
    def test_normal_text_no_tables(self):
        """正常文本无表格。"""
        text = "工作经历：负责核心接口设计"
        issues = _scan_tables_from_text(text, "工作经历")
        assert len(issues) == 0

    def test_markdown_table_detected(self):
        """检测到 Markdown 表格。"""
        text = "| 项目 | 技术 |\n| --- | --- |\n| 系统 | Python |"
        issues = _scan_tables_from_text(text, "项目经历")
        assert any(i.issue_type == AtsIssueType.table for i in issues)


# ═══════════════════════════════════════════════════════════
# _score 评分测试
# ═══════════════════════════════════════════════════════════


class TestScore:
    def test_no_issues_perfect_score(self):
        """无问题 → 100 分。"""
        assert _score([]) == 100

    def test_one_high_issue(self):
        """1 个 high → 80 分。"""
        from schemas.resume import AtsAuditIssue
        issues = [AtsAuditIssue(
            section="全文", issue_type=AtsIssueType.garbled,
            severity="high", message="乱码", suggestion="修复",
        )]
        assert _score(issues) == 80

    def test_one_medium_issue(self):
        """1 个 medium → 90 分。"""
        from schemas.resume import AtsAuditIssue
        issues = [AtsAuditIssue(
            section="全文", issue_type=AtsIssueType.special_symbol,
            severity="medium", message="符号", suggestion="修复",
        )]
        assert _score(issues) == 90

    def test_one_low_issue(self):
        """1 个 low → 96 分。"""
        from schemas.resume import AtsAuditIssue
        issues = [AtsAuditIssue(
            section="全文", issue_type=AtsIssueType.blank,
            severity="low", message="空行", suggestion="修复",
        )]
        assert _score(issues) == 96

    def test_multiple_issues(self):
        """多个问题累加扣分。"""
        from schemas.resume import AtsAuditIssue
        issues = [
            AtsAuditIssue(section="全文", issue_type=AtsIssueType.garbled,
                          severity="high", message="乱码", suggestion="修复"),
            AtsAuditIssue(section="全文", issue_type=AtsIssueType.garbled,
                          severity="high", message="乱码2", suggestion="修复"),
            AtsAuditIssue(section="全文", issue_type=AtsIssueType.table,
                          severity="medium", message="表格", suggestion="修复"),
        ]
        # 100 - 20*2 - 10*1 = 50
        assert _score(issues) == 50

    def test_score_clamp_at_zero(self):
        """得分不低于 0。"""
        from schemas.resume import AtsAuditIssue
        issues = [
            AtsAuditIssue(section="全文", issue_type=AtsIssueType.garbled,
                          severity="high", message=f"问题{i}", suggestion="修复")
            for i in range(10)
        ]
        assert _score(issues) == 0


# ═══════════════════════════════════════════════════════════
# _dedup_issues 去重测试
# ═══════════════════════════════════════════════════════════


class TestDedupIssues:
    def test_no_duplicates(self):
        """无重复问题。"""
        from schemas.resume import AtsAuditIssue
        issues = [
            AtsAuditIssue(section="全文", issue_type=AtsIssueType.garbled,
                          severity="high", message="问题1", suggestion="修复"),
            AtsAuditIssue(section="全文", issue_type=AtsIssueType.garbled,
                          severity="high", message="问题2", suggestion="修复"),
        ]
        result = _dedup_issues(issues)
        assert len(result) == 2

    def test_duplicates_removed(self):
        """重复问题被去除。"""
        from schemas.resume import AtsAuditIssue
        issue = AtsAuditIssue(section="全文", issue_type=AtsIssueType.garbled,
                              severity="high", message="乱码", suggestion="修复")
        issues = [issue, issue, issue]
        result = _dedup_issues(issues)
        assert len(result) == 1


# ═══════════════════════════════════════════════════════════
# _HtmlSectionParser 测试
# ═══════════════════════════════════════════════════════════


class TestHtmlSectionParser:
    def test_parse_simple_html(self):
        """解析简单 HTML。"""
        html = """
        <section class="module module-education">
            <h2 class="module-title">教育背景</h2>
            <div class="module-content">北京大学 计算机科学</div>
        </section>
        <section class="module module-skills">
            <h2 class="module-title">专业技能</h2>
            <div class="module-content">Python FastAPI</div>
        </section>
        """
        parser = _HtmlSectionParser()
        parser.feed(html)
        sections = parser.get_sections()
        assert len(sections) == 2
        assert sections[0]["section"] == "教育背景"
        assert "北京大学" in sections[0]["text"]
        assert sections[1]["section"] == "专业技能"
        assert "Python" in sections[1]["text"]

    def test_skip_script_and_style(self):
        """跳过 script 和 style 标签。"""
        html = """
        <h2 class="module-title">教育背景</h2>
        <div class="module-content">北京大学</div>
        <script>alert('xss')</script>
        <style>.hidden { display: none; }</style>
        """
        parser = _HtmlSectionParser()
        parser.feed(html)
        sections = parser.get_sections()
        assert len(sections) == 1
        assert "alert" not in sections[0]["text"]
        assert ".hidden" not in sections[0]["text"]

    def test_empty_section(self):
        """空节段。"""
        html = '<h2 class="module-title">荣誉奖项</h2>'
        parser = _HtmlSectionParser()
        parser.feed(html)
        sections = parser.get_sections()
        assert len(sections) == 1
        assert sections[0]["section"] == "荣誉奖项"
        assert sections[0]["text"] == ""


# ═══════════════════════════════════════════════════════════
# _audit_html 集成测试
# ═══════════════════════════════════════════════════════════


class TestAuditHtml:
    def test_clean_html_no_issues(self):
        """干净 HTML 无问题。"""
        html = """
        <section class="module module-education">
            <h2 class="module-title">教育背景</h2>
            <div class="module-content">北京大学 计算机科学 2018-2022</div>
        </section>
        """
        issues = _audit_html(html)
        # 可能有低级别的空行问题，但不应有 high 级别
        high_issues = [i for i in issues if i.severity == "high"]
        assert len(high_issues) == 0

    def test_html_with_replacement_char(self):
        """含替换字符的 HTML。"""
        html = """
        <section class="module module-education">
            <h2 class="module-title">教育背景</h2>
            <div class="module-content">北京大学�计算机科学</div>
        </section>
        """
        issues = _audit_html(html)
        assert any(i.issue_type == AtsIssueType.garbled for i in issues)

    def test_html_with_special_symbols(self):
        """含特殊符号的 HTML。"""
        html = """
        <section class="module module-skills">
            <h2 class="module-title">专业技能</h2>
            <div class="module-content">● Python ● FastAPI ★ 5年经验</div>
        </section>
        """
        issues = _audit_html(html)
        assert any(i.issue_type == AtsIssueType.special_symbol for i in issues)
