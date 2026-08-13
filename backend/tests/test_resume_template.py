"""简历模板注册/渲染 + CSS 变量预解析 测试。

测试范围：
- TemplateRegistry 模板注册/获取/列表
- CSS var() 预解析（var(--accent-color) → #2563eb 等）
- 15 种 module_type 各自渲染器
- 未知 module_type 兜底渲染
- 3 套模板渲染（default/minimal/business）
- 空模块/空内容跳过
- HTML 转义（XSS 防御）
- render_resume_from_dict
"""


from schemas.resume_module import ResumeStyle
from services.resume_template import (
    TemplateRegistry,
    _build_css_vars,
    _format_date_range,
    _render_fallback,
    _render_md,
    preparse_css_variables,
    render_module,
    render_resume_from_dict,
)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _basic_info_content():
    return {"name": "张三", "phone": "13800138000", "email": "zhangsan@test.com", "location": "广州"}


def _education_content():
    return {"entries": [{"school": "广东海洋大学", "degree": "本科", "major": "软件工程", "start_date": "2023-09", "end_date": "2027-06"}]}


def _work_content():
    return {"entries": [{"company": "字节跳动", "position": "后端实习生", "start_date": "2025-06", "end_date": "2025-09", "description": "负责 API 开发", "achievements": ["优化了查询性能", "修复了 10+ bug"]}]}


def _skills_content():
    return {"categories": [{"name": "编程语言", "items": ["Python", "JavaScript"]}, {"name": "框架", "items": ["FastAPI", "React"]}]}


def _full_modules():
    """覆盖所有 15 种 module_type 的模块列表。"""
    return [
        {"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0},
        {"module_type": "education", "content": _education_content(), "sort_order": 1},
        {"module_type": "work_experience", "content": _work_content(), "sort_order": 2},
        {"module_type": "project_experience", "content": {"entries": [{"name": "AI 简历分析器", "role": "全栈开发", "description": "从零搭建", "tech_stack": ["Python", "FastAPI", "React"], "url": "https://github.com/test/repo"}]}, "sort_order": 3},
        {"module_type": "skills", "content": _skills_content(), "sort_order": 4},
        {"module_type": "language", "content": {"entries": [{"name": "英语", "proficiency": "CET-6", "score": "436"}]}, "sort_order": 5},
        {"module_type": "honors", "content": {"entries": [{"title": "国家奖学金", "date": "2024-10", "description": "全系第一"}]}, "sort_order": 6},
        {"module_type": "certificates", "content": {"entries": [{"name": "软考中级", "issuer": "工信部", "date": "2024-06", "score": "合格"}]}, "sort_order": 7},
        {"module_type": "interests", "content": {"items": ["阅读", "跑步", "摄影"]}, "sort_order": 8},
        {"module_type": "club_activities", "content": {"entries": [{"name": "计算机协会", "role": "技术部长", "start_date": "2023-09", "end_date": "2024-06", "description": "组织技术分享会"}]}, "sort_order": 9},
        {"module_type": "publications", "content": {"entries": [{"title": "基于 RAG 的简历分析系统", "authors": ["张三", "李四"], "venue": "ICCSMT 2024", "date": "2024-12"}]}, "sort_order": 10},
        {"module_type": "recommendation", "content": {"entries": [{"name": "王教授", "title": "教授", "organization": "广东海洋大学", "contact": "13800138001", "email": "wang@test.com"}]}, "sort_order": 11},
        {"module_type": "social_links", "content": {"github": "https://github.com/test", "linkedin": "https://linkedin.com/in/test"}, "sort_order": 12},
        {"module_type": "other", "content": {"title": "自我评价", "content": "热爱技术，善于学习"}, "sort_order": 13},
        {"module_type": "custom", "content": {"title": "个人项目", "content": "独立开发了 3 个 Web 应用"}, "sort_order": 14},
    ]


# ═══════════════════════════════════════════════════════════
# TemplateRegistry
# ═══════════════════════════════════════════════════════════


class TestTemplateRegistry:
    """模板注册表。"""

    def test_list_names_contains_templates(self):
        """注册表包含全部新生成模板。"""
        names = TemplateRegistry.list_names()
        assert "default" in names
        assert "azurill" in names
        assert "serif" in names
        assert "compact-cn" in names
        assert len(names) >= 18

    def test_get_default_template(self):
        """获取 default 模板。"""
        html = TemplateRegistry.get("default")
        assert "<html" in html
        assert "{{modules}}" in html

    def test_get_sidebar_template(self):
        """获取侧栏模板（含 {{sidebar}} 分流）。"""
        html = TemplateRegistry.get("azurill")
        assert "<html" in html
        assert "{{modules}}" in html
        assert "{{sidebar}}" in html

    def test_get_banner_template(self):
        """获取头带模板（含 {{basic_header}}）。"""
        html = TemplateRegistry.get("executive")
        assert "<html" in html
        assert "{{basic_header}}" in html

    def test_get_unknown_template_falls_back_to_default(self):
        """未知 template_id（存量旧模板下线后）→ 兜底返回 default，不抛异常。"""
        fallback = TemplateRegistry.get("minimal")
        default = TemplateRegistry.get("default")
        assert fallback == default
        assert "<html" in fallback

    def test_render_unknown_template_falls_back(self):
        """存量简历用已下线旧模板 id 渲染 → 落到默认模板，不 500。"""
        html = render_resume_from_dict(_full_modules(), ResumeStyle(template_id="professional"))
        assert "<html" in html
        assert "张三" in html

    def test_templates_contain_css_vars(self):
        """模板 CSS 中包含 var() 引用。"""
        for name in ["default", "azurill", "serif", "ditto"]:
            html = TemplateRegistry.get(name)
            assert "var(--font-family)" in html
            assert "var(--font-size)" in html
            assert "var(--accent-color)" in html


# ═══════════════════════════════════════════════════════════
# CSS 变量预解析
# ═══════════════════════════════════════════════════════════


class TestPreparseCssVariables:
    """CSS var() 服务端预解析。"""

    def test_basic_variable_replacement(self):
        """var(--accent-color) → 实际值。"""
        style = ResumeStyle(accent_color="#ff0000")
        html = "color: var(--accent-color);"
        result = preparse_css_variables(html, style)
        assert "var(--accent-color)" not in result
        assert "#ff0000" in result

    def test_font_family_replacement(self):
        """var(--font-family) → 实际值。"""
        style = ResumeStyle(font_family="SimSun")
        html = "font-family: var(--font-family), sans-serif;"
        result = preparse_css_variables(html, style)
        assert "var(--font-family)" not in result
        assert "SimSun" in result

    def test_font_size_replacement(self):
        """var(--font-size) → 实际值。"""
        style = ResumeStyle(font_size="16px")
        html = "font-size: var(--font-size);"
        result = preparse_css_variables(html, style)
        assert "16px" in result
        assert "var(--font-size)" not in result

    def test_line_height_replacement(self):
        """var(--line-height) → 实际值。"""
        style = ResumeStyle(line_height=2.0)
        html = "line-height: var(--line-height);"
        result = preparse_css_variables(html, style)
        assert "2.0" in result
        assert "var(--line-height)" not in result

    def test_spacing_replacement(self):
        """var(--spacing) → 实际值。"""
        style = ResumeStyle(spacing="12px")
        html = "margin-bottom: var(--spacing);"
        result = preparse_css_variables(html, style)
        assert "12px" in result
        assert "var(--spacing)" not in result

    def test_multiple_variables_in_one_html(self):
        """一个 HTML 中多个 var() 同时替换。"""
        style = ResumeStyle(accent_color="#00ff00", font_size="18px", font_family="Arial")
        html = """
        body { font-family: var(--font-family); font-size: var(--font-size); }
        h1 { color: var(--accent-color); }
        """
        result = preparse_css_variables(html, style)
        assert "var(" not in result
        assert "#00ff00" in result
        assert "18px" in result
        assert "Arial" in result

    def test_unknown_variable_kept_as_is(self):
        """未知的 var(--xxx) 保持原样。"""
        style = ResumeStyle()
        html = "color: var(--unknown-var);"
        result = preparse_css_variables(html, style)
        assert "var(--unknown-var)" in result

    def test_no_variables_passthrough(self):
        """没有 var() 的 HTML 原样返回。"""
        style = ResumeStyle()
        html = "<div>hello</div>"
        result = preparse_css_variables(html, style)
        assert result == html

    def test_build_css_vars(self):
        """_build_css_vars 返回正确的字典。"""
        style = ResumeStyle(
            font_family="SimSun",
            font_size="16px",
            line_height=1.8,
            spacing="10px",
            accent_color="#abc123",
        )
        css_vars = _build_css_vars(style)
        assert css_vars["--font-family"] == "SimSun"
        assert css_vars["--font-size"] == "16px"
        assert css_vars["--line-height"] == "1.8"
        assert css_vars["--spacing"] == "10px"
        assert css_vars["--accent-color"] == "#abc123"


# ═══════════════════════════════════════════════════════════
# 模块渲染器（15 种 module_type）
# ═══════════════════════════════════════════════════════════


class TestModuleRenderers:
    """15 种 module_type 渲染器。"""

    def test_basic_info(self):
        html = render_module("basic_info", _basic_info_content())
        assert "张三" in html
        assert "13800138000" in html
        assert "zhangsan@test.com" in html

    def test_education(self):
        html = render_module("education", _education_content())
        assert "广东海洋大学" in html
        assert "本科" in html
        assert "软件工程" in html
        assert "2023-09" in html

    def test_work_experience(self):
        html = render_module("work_experience", _work_content())
        assert "字节跳动" in html
        assert "后端实习生" in html
        assert "优化了查询性能" in html

    def test_project_experience(self):
        html = render_module("project_experience", {"entries": [{"name": "AI 系统", "role": "开发", "tech_stack": ["Python", "FastAPI"]}]})
        assert "AI 系统" in html
        assert "开发" in html
        assert "Python" in html

    def test_project_link_is_clickable_and_unsafe_scheme_is_rejected(self):
        safe_html = render_module(
            "project_experience",
            {"entries": [{"name": "Repo", "url": "https://github.com/test/repo"}]},
        )
        unsafe_html = render_module(
            "project_experience",
            {"entries": [{"name": "Bad", "url": "javascript:alert(1)"}]},
        )
        assert 'href="https://github.com/test/repo"' in safe_html
        assert "javascript:" not in unsafe_html

    def test_skills(self):
        html = render_module("skills", _skills_content())
        assert "编程语言" in html
        assert "Python" in html
        assert "框架" in html
        assert "FastAPI" in html

    def test_language(self):
        html = render_module("language", {"entries": [{"name": "英语", "proficiency": "CET-6", "score": "436"}]})
        assert "英语" in html
        assert "CET-6" in html
        assert "436" in html

    def test_honors(self):
        html = render_module("honors", {"entries": [{"title": "国家奖学金", "date": "2024-10"}]})
        assert "国家奖学金" in html
        assert "2024-10" in html

    def test_certificates(self):
        html = render_module("certificates", {"entries": [{"name": "软考中级", "issuer": "工信部"}]})
        assert "软考中级" in html
        assert "工信部" in html

    def test_interests(self):
        html = render_module("interests", {"items": ["阅读", "跑步"]})
        assert "阅读" in html
        assert "跑步" in html

    def test_club_activities(self):
        html = render_module("club_activities", {"entries": [{"name": "计算机协会", "role": "部长"}]})
        assert "计算机协会" in html
        assert "部长" in html

    def test_publications(self):
        html = render_module("publications", {"entries": [{"title": "RAG 论文", "authors": ["张三"], "venue": "ICCSMT"}]})
        assert "RAG 论文" in html
        assert "张三" in html
        assert "ICCSMT" in html

    def test_recommendation(self):
        html = render_module("recommendation", {"entries": [{"name": "王教授", "title": "教授", "email": "wang@test.com"}]})
        assert "王教授" in html
        assert "教授" in html
        assert "wang@test.com" in html

    def test_social_links(self):
        html = render_module("social_links", {"github": "https://github.com/test"})
        assert "GitHub" in html
        assert "https://github.com/test" in html

    def test_other(self):
        html = render_module("other", {"title": "自我评价", "content": "热爱技术"})
        assert "自我评价" in html
        assert "热爱技术" in html

    def test_custom(self):
        html = render_module("custom", {"title": "补充信息", "content": "自定义内容"})
        assert "补充信息" in html
        assert "自定义内容" in html

    def test_custom_multi_entries(self):
        """自定义模块多板块（entries）渲染 — """
        html = render_module(
            "custom",
            {
                "entries": [
                    {"title": "项目亮点", "content": "独立开发 3 个 Web 应用"},
                    {"title": "开源贡献", "content": "维护 2 个开源项目"},
                ]
            },
        )
        assert "项目亮点" in html
        assert "独立开发 3 个 Web 应用" in html
        assert "开源贡献" in html
        assert "维护 2 个开源项目" in html

    def test_custom_multi_entries_skips_empty(self):
        """多板块模式跳过空内容条目。"""
        html = render_module(
            "custom",
            {
                "entries": [
                    {"title": "有内容", "content": "正文"},
                    {"title": "空板块", "content": ""},
                ]
            },
        )
        assert "有内容" in html
        assert "正文" in html
        assert "空板块" not in html


# ═══════════════════════════════════════════════════════════
# 兜底渲染
# ═══════════════════════════════════════════════════════════


class TestFallbackRenderer:
    """未知 module_type 兜底渲染。"""

    def test_unknown_module_type_uses_fallback(self):
        """未知 module_type 走兜底渲染。"""
        html = render_module("unknown_type", {"key1": "value1", "key2": "value2"})
        assert "key1" in html
        assert "value1" in html
        assert "key2" in html
        assert "value2" in html

    def test_fallback_with_nested_dict(self):
        """兜底渲染处理嵌套 dict。"""
        html = _render_fallback("unknown", {"items": ["a", "b"], "name": "test"})
        assert "items" in html
        assert "a" in html
        assert "b" in html
        assert "test" in html

    def test_fallback_skips_empty_values(self):
        """兜底渲染跳过空值。"""
        html = _render_fallback("unknown", {"a": "", "b": None, "c": [], "d": "valid"})
        assert "a" not in html or 'a""' not in html
        assert "valid" in html

    def test_fallback_empty_content(self):
        """兜底渲染空 content 返回空字符串。"""
        assert _render_fallback("unknown", {}) == ""


# ═══════════════════════════════════════════════════════════
# 完整渲染
# ═══════════════════════════════════════════════════════════


class TestRenderResume:
    """完整简历渲染。"""

    def test_render_with_default_template(self):
        """使用 default 模板渲染。"""
        html = render_resume_from_dict(_full_modules(), ResumeStyle(template_id="default"))
        assert "<html" in html
        assert "张三" in html
        assert "广东海洋大学" in html
        assert "字节跳动" in html
        assert "Python" in html
        # CSS 变量已预解析
        assert "var(--font-family)" not in html
        assert "var(--accent-color)" not in html

    def test_render_with_sidebar_template(self):
        """使用侧栏模板（azurill）渲染，侧栏模块进 {{sidebar}}。"""
        html = render_resume_from_dict(_full_modules(), ResumeStyle(template_id="azurill"))
        assert "<html" in html
        assert "张三" in html
        assert "var(" not in html
        # 侧栏类模块（技能）出现在 sidebar 容器内
        assert 'class="sidebar"' in html
        assert "专业技能" in html

    def test_render_all_templates_integrity(self):
        """遍历全部模板渲染 → 无占位符残留 / 无 var() 残留 / 无 grid。"""
        for name in TemplateRegistry.list_names():
            html = render_resume_from_dict(_full_modules(), ResumeStyle(template_id=name))
            assert "<html" in html, name
            assert "{{" not in html, f"{name} 残留 {{ 占位符"
            assert "var(" not in html, f"{name} 残留 var()"
            assert "display:grid" not in html, f"{name} 含 grid"

    def test_render_repeats_page_container_decoration(self):
        html = render_resume_from_dict(_full_modules(), ResumeStyle(template_id="default"))
        assert "box-decoration-break: clone" in html

    def test_render_with_banner_template(self):
        """使用头带模板（executive）渲染，basic_info 进 {{basic_header}}。"""
        html = render_resume_from_dict(_full_modules(), ResumeStyle(template_id="executive"))
        assert "<html" in html
        assert "张三" in html
        assert 'class="banner"' in html
        assert "var(" not in html

    def test_render_with_custom_style(self):
        """自定义样式渲染。"""
        style = ResumeStyle(
            template_id="default",
            accent_color="#ff6600",
            font_size="16px",
            font_family="SimSun",
            line_height=2.0,
            spacing="12px",
        )
        html = render_resume_from_dict(_full_modules(), style)
        assert "#ff6600" in html
        assert "16px" in html
        assert "SimSun" in html
        assert "2.0" in html
        assert "12px" in html
        assert "var(" not in html

    def test_render_empty_modules(self):
        """空模块列表渲染。"""
        html = render_resume_from_dict([], ResumeStyle())
        assert "<html" in html
        assert "{{modules}}" not in html

    def test_render_skips_empty_content_modules(self):
        """空内容模块被跳过。"""
        modules = [
            {"module_type": "basic_info", "content": {"name": "张三"}, "sort_order": 0},
            {"module_type": "education", "content": {"entries": []}, "sort_order": 1},
            {"module_type": "skills", "content": {"categories": []}, "sort_order": 2},
        ]
        html = render_resume_from_dict(modules, ResumeStyle())
        assert "张三" in html
        assert "教育背景" not in html
        assert "专业技能" not in html

    def test_render_filename_in_title(self):
        """filename 出现在 <title> 中。"""
        html = render_resume_from_dict(_full_modules(), ResumeStyle(), filename="我的简历")
        assert "我的简历" in html

    def test_render_hidden_modules(self):
        """hidden_modules 中的模块类型不渲染。"""
        style = ResumeStyle(template_id="default", hidden_modules=["interests", "social_links"])
        html = render_resume_from_dict(_full_modules(), style)
        assert "张三" in html
        assert "兴趣爱好" not in html
        assert "阅读" not in html
        assert "社交链接" not in html
        # social_links 独有字段（project 的 github url 仍在，故用 linkedin 断言）
        assert "linkedin" not in html

    def test_render_hidden_modules_empty(self):
        """hidden_modules 为空时全部渲染。"""
        style = ResumeStyle(template_id="default", hidden_modules=[])
        html = render_resume_from_dict(_full_modules(), style)
        assert "兴趣爱好" in html
        assert "社交链接" in html
        assert "<title>" in html

    def test_render_unknown_template_falls_back(self):
        """未知模板 → 兜底默认模板渲染，不抛异常。"""
        html = render_resume_from_dict(_full_modules(), ResumeStyle(template_id="nonexistent"))
        assert "<html" in html
        assert "张三" in html

    def test_render_modules_sorted(self):
        """模块按 sort_order 排序。"""
        modules = [
            {"module_type": "skills", "content": _skills_content(), "sort_order": 2},
            {"module_type": "basic_info", "content": _basic_info_content(), "sort_order": 0},
            {"module_type": "education", "content": _education_content(), "sort_order": 1},
        ]
        html = render_resume_from_dict(modules, ResumeStyle())
        basic_pos = html.index("张三")
        edu_pos = html.index("广东海洋大学")
        skills_pos = html.index("编程语言")
        assert basic_pos < edu_pos < skills_pos


# ═══════════════════════════════════════════════════════════
# HTML 转义（XSS 防御）
# ═══════════════════════════════════════════════════════════


class TestHtmlEscape:
    """HTML 转义防御 XSS。"""

    def test_basic_info_escapes_html(self):
        """basic_info 中的 HTML 标签被转义。"""
        html = render_module("basic_info", {"name": "<script>alert(1)</script>"})
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_other_module_escapes_html(self):
        """other 模块中的 HTML 被转义。"""
        html = render_module("other", {"content": "<img src=x onerror=alert(1)>"})
        assert "<img" not in html
        assert "&lt;img" in html

    def test_custom_module_escapes_html(self):
        """custom 模块中的 HTML 被转义。"""
        html = render_module("custom", {"title": "标题", "content": "<b>bold</b>"})
        assert "<b>bold</b>" not in html
        assert "&lt;b&gt;" in html


# ═══════════════════════════════════════════════════════════
# Markdown 渲染（_render_md）
# ═══════════════════════════════════════════════════════════


class TestMarkdownRendering:
    """长文本字段的 Markdown 渲染 — 格式化为 HTML 而非字面量标记。"""

    def test_bold_renders_strong(self):
        """**加粗** → <strong>。"""
        html = render_module("other", {"content": "**加粗** 文本"})
        assert "<strong>加粗</strong>" in html

    def test_list_renders_ul(self):
        """- 列表项 → <ul>/<li>。"""
        html = render_module("custom", {"content": "- 第一项\n- 第二项"})
        assert "<ul>" in html
        assert "<li>第一项</li>" in html
        assert "<li>第二项</li>" in html

    def test_xss_script_still_escaped(self):
        """<script> 在 Markdown 字段中仍被转义，真实标签不出现。"""
        html = render_module("other", {"content": "<script>alert(1)</script>"})
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_xss_img_still_escaped(self):
        """<img onerror> 在 Markdown 字段中仍被转义。"""
        html = render_module("custom", {"content": "<img src=x onerror=alert(1)>"})
        assert "<img" not in html
        assert "&lt;img" in html

    def test_summary_renders_markdown(self):
        """basic_info.summary 渲染 Markdown。"""
        html = render_module("basic_info", {"summary": "**加粗** 摘要"})
        assert "<strong>加粗</strong>" in html

    def test_work_description_renders_markdown(self):
        """work_experience.description 渲染 Markdown。"""
        html = render_module(
            "work_experience",
            {"entries": [{"company": "字节跳动", "description": "- 成就一\n- 成就二"}]},
        )
        assert "<ul>" in html
        assert "<li>成就一</li>" in html
        assert "<li>成就二</li>" in html

    def test_short_fields_not_rendered_as_markdown(self):
        """短字段（company 等）保持纯文本转义，不做 Markdown 展开。"""
        html = render_module(
            "work_experience",
            {"entries": [{"company": "**不是加粗**", "description": "描述"}]},
        )
        assert "<strong>" not in html
        assert "**不是加粗**" in html

    def test_render_md_none_and_empty(self):
        """_render_md 空值/None 返回空串，与 _esc 一致。"""
        assert _render_md(None) == ""
        assert _render_md("") == ""

    def test_render_md_plain_text(self):
        """纯文本经 Markdown 渲染后保留原文。"""
        assert "热爱技术" in _render_md("热爱技术")


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════


class TestFormatDateRange:
    """日期范围格式化。"""

    def test_both_dates(self):
        assert _format_date_range("2023-09", "2027-06") == "2023-09 - 2027-06"

    def test_start_only(self):
        assert _format_date_range("2023-09", None) == "2023-09 - 至今"

    def test_end_only(self):
        assert _format_date_range(None, "2027-06") == "2027-06"

    def test_both_none(self):
        assert _format_date_range(None, None) == ""
