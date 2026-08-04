"""T25: 简历模板注册/渲染 + CSS 变量服务端预解析。

职责：
- 从 backend/templates/ 加载 3 套 HTML 模板（default/minimal/business）
- 将 ResumeModule 列表渲染为 HTML（15 种 module_type 各有渲染器，未知类型兜底）
- CSS var() 服务端预解析（WeasyPrint 不支持 CSS custom properties）

设计依据：
- spec 第 228 行：模板渲染器对未知 module_type 有兜底分支
- spec 第 270 行：ResumeStyle = {template_id, font_family, font_size, line_height, spacing, accent_color}
- plan.md 风险表：WeasyPrint CSS 兼容（var()/flexbox）→ T25 服务端预解析变量
"""

import logging
import re
from html import escape
from pathlib import Path

from schemas.resume_module import ResumeStyle, DEFAULT_MODULE_LABELS, get_content_items, get_content_title

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# CSS var(--name) 匹配模式
_CSS_VAR_PATTERN = re.compile(r"var\(--([\w-]+)\)")

# ResumeStyle 字段 → CSS 变量名映射
_STYLE_TO_CSS_VAR: dict[str, str] = {
    "font_family": "--font-family",
    "font_size": "--font-size",
    "line_height": "--line-height",
    "spacing": "--spacing",
    "accent_color": "--accent-color",
    "margin": "--margin",
    "page_size": "--page-size",
    "section_spacing": "--section-spacing",
}

# 默认 CSS 变量值（style 字段缺失时兜底）
_DEFAULT_CSS_VARS: dict[str, str] = {
    "--font-family": "Noto Sans CJK SC",
    "--font-size": "14px",
    "--line-height": "1.6",
    "--spacing": "8px",
    "--accent-color": "#2563eb",
    "--margin": "16mm",
    "--page-size": "A4",
    "--section-spacing": "16px",
}

# module_type → 中文节标题
_MODULE_TITLES: dict[str, str] = {
    "basic_info": "个人简介",
    "education": "教育背景",
    "work_experience": "工作经历",
    "project_experience": "项目经历",
    "skills": "专业技能",
    "language": "语言能力",
    "honors": "荣誉奖项",
    "certificates": "证书",
    "interests": "兴趣爱好",
    "club_activities": "社团活动",
    "publications": "研究成果",
    "recommendation": "推荐人",
    "social_links": "社交链接",
    "other": "其他",
    "custom": "自定义",
}


# ═══════════════════════════════════════════════════════════
# 模板注册表
# ═══════════════════════════════════════════════════════════


class TemplateRegistry:
    """模板注册表 — 从 templates/ 目录加载 HTML 模板。

    模板文件约定：
    - 放在 backend/templates/ 目录
    - 文件名即模板 ID（如 default.html → template_id="default"）
    - HTML 中包含 {{modules}} 占位符（渲染时替换为模块 HTML）
    - CSS 中使用 var(--xxx) 引用样式变量（渲染时预解析为实际值）
    """

    _templates: dict[str, str] = {}
    _loaded: bool = False
    # 模板目录文件签名（(文件名, mtime_ns) 元组），变化时自动重扫——
    # 支持运行时新增/修改模板文件，无需重启后端进程
    _signature: tuple = ()

    @classmethod
    def _ensure_loaded(cls) -> None:
        """懒加载 + 文件变化检测：模板目录文件有增删改时重新扫描。"""
        if not TEMPLATES_DIR.exists():
            logger.warning("Templates directory not found: %s", TEMPLATES_DIR)
            cls._templates = {}
            return

        signature = tuple(
            sorted((f.name, f.stat().st_mtime_ns) for f in TEMPLATES_DIR.glob("*.html"))
        )
        if signature == cls._signature and cls._loaded:
            return

        for html_file in TEMPLATES_DIR.glob("*.html"):
            name = html_file.stem
            cls._templates[name] = html_file.read_text(encoding="utf-8")
            logger.info("Loaded template: %s", name)
        cls._signature = signature
        cls._loaded = True

    @classmethod
    def get(cls, name: str) -> str:
        """获取模板 HTML 内容。

        Raises:
            ValueError: 模板不存在
        """
        cls._ensure_loaded()
        if name not in cls._templates:
            available = ", ".join(cls._templates.keys()) or "(无可用模板)"
            raise ValueError(f"未知模板: {name}，可用模板: {available}")
        return cls._templates[name]

    @classmethod
    def list_names(cls) -> list[str]:
        """列出所有已注册模板名。"""
        cls._ensure_loaded()
        return sorted(cls._templates.keys())

    @classmethod
    def _reset_for_test(cls) -> None:
        """测试用：重置注册表状态。"""
        cls._templates.clear()
        cls._loaded = False
        cls._signature = ()


# ═══════════════════════════════════════════════════════════
# CSS 变量预解析
# ═══════════════════════════════════════════════════════════


def _build_css_vars(style: ResumeStyle) -> dict[str, str]:
    """从 ResumeStyle 构建 CSS 变量字典。"""
    css_vars = _DEFAULT_CSS_VARS.copy()
    css_vars["--font-family"] = style.font_family
    css_vars["--font-size"] = style.font_size
    css_vars["--line-height"] = str(style.line_height)
    css_vars["--spacing"] = style.spacing
    css_vars["--accent-color"] = style.accent_color
    css_vars["--margin"] = style.margin
    css_vars["--page-size"] = style.page_size
    css_vars["--section-spacing"] = style.section_spacing
    return css_vars


def preparse_css_variables(html: str, style: ResumeStyle) -> str:
    """将 HTML 中所有 CSS var(--xxx) 替换为实际值。

    WeasyPrint 不支持 CSS custom properties（var()），
    需在服务端将 var(--accent-color) 等替换为 #2563eb 等实际值。

    未知的 var(--xxx) 保持原样（不替换），便于调试。
    """
    css_vars = _build_css_vars(style)

    def _replacer(match: re.Match) -> str:
        var_name = f"--{match.group(1)}"
        return css_vars.get(var_name, match.group(0))

    return _CSS_VAR_PATTERN.sub(_replacer, html)


# ═══════════════════════════════════════════════════════════
# 模块渲染器（15 种 module_type + 兜底）
# ═══════════════════════════════════════════════════════════


def _esc(value) -> str:
    """HTML 转义。"""
    if value is None:
        return ""
    return escape(str(value))


try:
    import markdown as _markdown

    def _render_md(value) -> str:
        """渲染 Markdown 为 HTML（先 html.escape 防 XSS）。

        编辑器（Tiptap WYSIWYG）存储 Markdown，渲染时先转义再交给
        python-markdown —— 已转义的实体不会被 markdown 反转义成真实 HTML，
        因此 **加粗**、- 列表等标记会格式化为 <strong>/<ul>，而 <script> 保持转义。
        """
        if value is None:
            return ""
        return _markdown.markdown(
            escape(str(value)),
            extensions=["extra", "nl2br", "sane_lists"],
        )

except ImportError:  # pragma: no cover
    # markdown 库未安装时降级为纯 HTML 转义，行为与 _esc 一致
    _render_md = _esc


def _render_basic_info(content: dict) -> str:
    """渲染基本信息模块。"""
    parts = []

    # 头像 + 姓名行
    avatar = content.get("avatar")
    name = content.get("name", "")
    if name or avatar:
        header_parts = []
        if avatar:
            header_parts.append(
                f'<img class="basic-avatar" src="{_esc(avatar)}" alt="{_esc(name)}" '
                f'style="width:80px;height:80px;border-radius:50%;object-fit:cover;" />'
            )
        if name:
            header_parts.append(f'<div class="basic-name">{_esc(name)}</div>')
        parts.append(
            f'<div class="basic-header" style="display:flex;align-items:center;gap:12px;">'
            + "".join(header_parts) + "</div>"
        )

    # 求职意向
    if content.get("job_title"):
        parts.append(f'<div class="basic-job-title">{_esc(content["job_title"])}</div>')

    # 联系方式（电话 | 邮箱 | 所在城市 | 当前状态 | 籍贯）
    contact_parts = []
    if content.get("phone"):
        contact_parts.append(f'<span>{_esc(content["phone"])}</span>')
    if content.get("email"):
        contact_parts.append(f'<span>{_esc(content["email"])}</span>')
    if content.get("location"):
        contact_parts.append(f'<span>{_esc(content["location"])}</span>')
    if content.get("status"):
        contact_parts.append(f'<span>{_esc(content["status"])}</span>')
    if content.get("hometown"):
        contact_parts.append(f'<span>籍贯: {_esc(content["hometown"])}</span>')
    if contact_parts:
        parts.append(f'<div class="basic-contact">{" | ".join(contact_parts)}</div>')

    # 链接（GitHub | 博客 | 主页）
    link_parts = []
    if content.get("github_url"):
        link_parts.append(
            f'<a href="{_esc(content["github_url"])}" style="color:var(--accent-color);text-decoration:none;">GitHub</a>'
        )
    if content.get("blog_url"):
        link_parts.append(
            f'<a href="{_esc(content["blog_url"])}" style="color:var(--accent-color);text-decoration:none;">博客</a>'
        )
    if content.get("homepage_url"):
        link_parts.append(
            f'<a href="{_esc(content["homepage_url"])}" style="color:var(--accent-color);text-decoration:none;">主页</a>'
        )
    if link_parts:
        parts.append(f'<div class="basic-links">{" | ".join(link_parts)}</div>')

    if content.get("summary"):
        parts.append(f'<div class="basic-summary">{_render_md(content["summary"])}</div>')

    # #6: 自定义字段（预设字段之外的自定义键值对）
    custom_fields = content.get("custom_fields", [])
    if isinstance(custom_fields, list):
        valid_fields = [
            f for f in custom_fields
            if isinstance(f, dict) and f.get("key")
        ]
        if valid_fields:
            field_parts = []
            for f in valid_fields:
                field_parts.append(
                    f'<span><b>{_esc(f["key"])}</b>: {_esc(f.get("value", ""))}</span>'
                )
            parts.append(
                '<div class="basic-custom-fields">' + " | ".join(field_parts) + "</div>"
            )

    return "\n".join(parts) if parts else ""


def _render_education(content: dict) -> str:
    """渲染教育背景模块。"""
    entries = get_content_items(content)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        school = _esc(entry.get("school", ""))
        degree = _esc(entry.get("degree", ""))
        major = _esc(entry.get("major", ""))
        dates = _format_date_range(entry.get("start_date"), entry.get("end_date"))

        row = f'<div class="edu-item">'
        row += f'<div class="edu-header"><span class="edu-school">{school}</span>'
        if dates:
            row += f'<span class="edu-date">{dates}</span>'
        row += "</div>"
        info_parts = []
        if degree:
            info_parts.append(f'<span>{degree}</span>')
        if major:
            info_parts.append(f'<span>{major}</span>')
        if entry.get("gpa"):
            info_parts.append(f'<span>GPA: {_esc(entry["gpa"])}</span>')
        if info_parts:
            row += f'<div class="edu-info">{" | ".join(info_parts)}</div>'
        if entry.get("description"):
            row += f'<div class="edu-desc">{_render_md(entry["description"])}</div>'
        row += "</div>"
        rows.append(row)
    return "\n".join(rows)


def _render_work_experience(content: dict) -> str:
    """渲染工作经历模块。"""
    entries = get_content_items(content)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        company = _esc(entry.get("company", ""))
        position = _esc(entry.get("position", ""))
        dates = _format_date_range(entry.get("start_date"), entry.get("end_date"))

        row = '<div class="work-item">'
        row += '<div class="work-header">'
        row += f'<span class="work-company">{company}</span>'
        if position:
            row += f'<span class="work-position">{position}</span>'
        if dates:
            row += f'<span class="work-date">{dates}</span>'
        row += "</div>"
        if entry.get("description"):
            row += f'<div class="work-desc">{_render_md(entry["description"])}</div>'
        achievements = entry.get("achievements", [])
        if achievements:
            items = "".join(f"<li>{_render_md(a)}</li>" for a in achievements)
            row += f'<ul class="work-achievements">{items}</ul>'
        row += "</div>"
        rows.append(row)
    return "\n".join(rows)


def _render_project_experience(content: dict) -> str:
    """渲染项目经历模块。"""
    entries = get_content_items(content)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        name = _esc(entry.get("name", ""))
        role = _esc(entry.get("role", ""))
        dates = _format_date_range(entry.get("start_date"), entry.get("end_date"))

        row = '<div class="proj-item">'
        row += '<div class="proj-header">'
        row += f'<span class="proj-name">{name}</span>'
        if role:
            row += f'<span class="proj-role">{role}</span>'
        if dates:
            row += f'<span class="proj-date">{dates}</span>'
        row += "</div>"
        if entry.get("description"):
            row += f'<div class="proj-desc">{_render_md(entry["description"])}</div>'
        tech_stack = entry.get("tech_stack", [])
        if tech_stack:
            techs = ", ".join(_esc(t) for t in tech_stack)
            row += f'<div class="proj-tech">技术栈: {techs}</div>'
        if entry.get("url"):
            row += f'<div class="proj-url">{_esc(entry["url"])}</div>'
        row += "</div>"
        rows.append(row)
    return "\n".join(rows)


def _render_skills(content: dict) -> str:
    """渲染专业技能模块（v2：扁平 items + 熟练度）。"""
    items = get_content_items(content)
    if not items:
        # 兜底：旧格式 categories
        categories = content.get("categories", [])
        if not categories:
            return ""
        rows = []
        for cat in categories:
            name = _esc(cat.get("name", ""))
            cat_items = cat.get("items", [])
            if cat_items:
                items_html = "".join(
                    f'<span class="skill-item">{_esc(i)}</span>' for i in cat_items
                )
                rows.append(
                    f'<div class="skill-cat"><span class="skill-name">{name}</span> {items_html}</div>'
                )
        return "\n".join(rows) if rows else ""

    # 新格式：按 category 分组显示
    show_levels = content.get("show_levels", False)
    by_category: dict[str, list] = {}
    for item in items:
        cat = item.get("category", "") or "其他"
        by_category.setdefault(cat, []).append(item)

    rows = []
    for cat_name, cat_items in by_category.items():
        skill_spans = []
        for item in cat_items:
            name = _esc(item.get("name", ""))
            level = item.get("level")
            if show_levels and level:
                skill_spans.append(
                    f'<span class="skill-item">{name} '
                    f'<span class="skill-level">{"★" * level}{"☆" * (5 - level)}</span></span>'
                )
            else:
                skill_spans.append(f'<span class="skill-item">{name}</span>')
        rows.append(
            f'<div class="skill-cat"><span class="skill-name">{_esc(cat_name)}</span> '
            + "".join(skill_spans) + "</div>"
        )
    return "\n".join(rows) if rows else ""


def _render_language(content: dict) -> str:
    """渲染语言能力模块。"""
    entries = get_content_items(content)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        name = _esc(entry.get("name", ""))
        proficiency = _esc(entry.get("proficiency", ""))
        score = _esc(entry.get("score", ""))
        parts = [f"<strong>{name}</strong>"]
        if proficiency:
            parts.append(proficiency)
        if score:
            parts.append(score)
        rows.append(f'<div class="lang-item">{" - ".join(parts)}</div>')
    return "\n".join(rows)


def _render_honors(content: dict) -> str:
    """渲染荣誉奖项模块。"""
    entries = get_content_items(content)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        title = _esc(entry.get("title", ""))
        date = _esc(entry.get("date", ""))
        desc = _render_md(entry.get("description", ""))
        row = f'<div class="honor-item"><span class="honor-title">{title}</span>'
        if date:
            row += f'<span class="honor-date">{date}</span>'
        row += "</div>"
        if desc:
            row += f'<div class="honor-desc">{desc}</div>'
        rows.append(row)
    return "\n".join(rows)


def _render_certificates(content: dict) -> str:
    """渲染证书模块。"""
    entries = get_content_items(content)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        name = _esc(entry.get("name", ""))
        issuer = _esc(entry.get("issuer", ""))
        date = _esc(entry.get("date", ""))
        score = _esc(entry.get("score", ""))
        parts = [f"<strong>{name}</strong>"]
        if issuer:
            parts.append(issuer)
        if date:
            parts.append(date)
        if score:
            parts.append(f"成绩: {score}")
        rows.append(f'<div class="cert-item">{" - ".join(parts)}</div>')
    return "\n".join(rows)


def _render_interests(content: dict) -> str:
    """渲染兴趣爱好模块。"""
    raw_items = content.get("items", [])
    if not raw_items:
        return ""
    # 新格式：items 是 [{id, name}]；旧格式：items 是 string[]
    if raw_items and isinstance(raw_items[0], dict):
        names = [i.get("name", "") for i in raw_items if i.get("name")]
    else:
        names = [str(i) for i in raw_items if i]
    if not names:
        return ""
    return f'<div class="interests">{", ".join(_esc(n) for n in names)}</div>'


def _render_club_activities(content: dict) -> str:
    """渲染社团活动模块。"""
    entries = get_content_items(content)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        name = _esc(entry.get("name", ""))
        role = _esc(entry.get("role", ""))
        dates = _format_date_range(entry.get("start_date"), entry.get("end_date"))
        desc = _render_md(entry.get("description", ""))

        row = '<div class="club-item">'
        row += f'<span class="club-name">{name}</span>'
        if role:
            row += f'<span class="club-role">{role}</span>'
        if dates:
            row += f'<span class="club-date">{dates}</span>'
        row += "</div>"
        if desc:
            row += f'<div class="club-desc">{desc}</div>'
        rows.append(row)
    return "\n".join(rows)


def _render_publications(content: dict) -> str:
    """渲染研究成果模块。"""
    entries = get_content_items(content)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        title = _esc(entry.get("title", ""))
        authors = entry.get("authors", [])
        venue = _esc(entry.get("venue", ""))
        date = _esc(entry.get("date", ""))

        row = f'<div class="pub-item"><div class="pub-title">{title}</div>'
        if authors:
            authors_html = ", ".join(_esc(a) for a in authors)
            row += f'<div class="pub-authors">{authors_html}</div>'
        info_parts = []
        if venue:
            info_parts.append(venue)
        if date:
            info_parts.append(date)
        if info_parts:
            row += f'<div class="pub-info">{" - ".join(info_parts)}</div>'
        row += "</div>"
        rows.append(row)
    return "\n".join(rows)


def _render_recommendation(content: dict) -> str:
    """渲染推荐人模块。"""
    entries = get_content_items(content)
    if not entries:
        return ""
    rows = []
    for entry in entries:
        name = _esc(entry.get("name", ""))
        title = _esc(entry.get("title", ""))
        org = _esc(entry.get("organization", ""))
        contact = _esc(entry.get("contact", ""))
        email = _esc(entry.get("email", ""))

        parts = [f"<strong>{name}</strong>"]
        if title:
            parts.append(title)
        if org:
            parts.append(org)
        row = f'<div class="rec-item">{" - ".join(parts)}</div>'
        contact_parts = []
        if contact:
            contact_parts.append(contact)
        if email:
            contact_parts.append(email)
        if contact_parts:
            row += f'<div class="rec-contact">{" | ".join(contact_parts)}</div>'
        rows.append(row)
    return "\n".join(rows)


def _render_social_links(content: dict) -> str:
    """渲染社交链接模块（v2：items 数组）。"""
    items = get_content_items(content)
    if items:
        # 新格式
        parts = []
        for item in items:
            platform = _esc(item.get("platform", ""))
            url = _esc(item.get("url", ""))
            if platform or url:
                parts.append(f'<span class="social-link"><strong>{platform}</strong>: {url}</span>')
        return " | ".join(parts) if parts else ""

    # 旧格式兜底
    parts = []
    fields = [
        ("github", "GitHub"),
        ("linkedin", "LinkedIn"),
        ("website", "个人网站"),
        ("twitter", "Twitter"),
        ("wechat", "微信"),
    ]
    for key, label in fields:
        val = content.get(key)
        if val:
            parts.append(f'<span class="social-link"><strong>{label}</strong>: {_esc(val)}</span>')

    others = content.get("others", [])
    for other in others:
        if isinstance(other, dict):
            name = _esc(other.get("name", ""))
            url = _esc(other.get("url", ""))
            if name or url:
                parts.append(f'<span class="social-link"><strong>{name}</strong>: {url}</span>')

    return " | ".join(parts) if parts else ""


def _render_other(content: dict) -> str:
    """渲染其他模块。"""
    text = content.get("content", "")
    if not text:
        return ""
    title = content.get("title", "")
    html = ""
    if title:
        html += f'<div class="other-title">{_esc(title)}</div>'
    html += f'<div class="other-content">{_render_md(text)}</div>'
    return html


def _render_custom(content: dict) -> str:
    """渲染自定义模块 — 支持 items / entries / 单板块 向后兼容。"""
    # 新格式 items
    items = get_content_items(content)
    if items:
        parts = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = _esc(item.get("title", ""))
            text = _render_md(item.get("content", ""))
            if not text:
                continue
            if title:
                parts.append(f'<div class="custom-title">{title}</div>')
            parts.append(f'<div class="custom-content">{text}</div>')
        return "\n".join(parts)
    # 旧格式 entries
    entries = content.get("entries", [])
    if isinstance(entries, list) and entries:
        parts = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = _esc(entry.get("title", ""))
            text = _render_md(entry.get("content", ""))
            if not text:
                continue
            if title:
                parts.append(f'<div class="custom-title">{title}</div>')
            parts.append(f'<div class="custom-content">{text}</div>')
        return "\n".join(parts)
    # 单板块模式
    title = content.get("title", "")
    text = content.get("content", "")
    if not text:
        return ""
    html = ""
    if title:
        html += f'<div class="custom-title">{_esc(title)}</div>'
    html += f'<div class="custom-content">{_render_md(text)}</div>'
    return html


def _render_fallback(module_type: str, content: dict) -> str:
    """未知 module_type 兜底渲染 — 将 content JSON 平铺为键值对。

    spec 第 228 行：模板渲染器对未知 module_type 有兜底分支。
    """
    if not content:
        return ""
    rows = []
    for k, v in content.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, list):
            v_text = ", ".join(str(i) for i in v)
        else:
            v_text = str(v)
        rows.append(f'<div class="fallback-row"><span class="fallback-key">{_esc(k)}</span>: {_esc(v_text)}</div>')
    return "\n".join(rows) if rows else ""


# module_type → 渲染器映射
_MODULE_RENDERERS: dict[str, callable] = {
    "basic_info": _render_basic_info,
    "education": _render_education,
    "work_experience": _render_work_experience,
    "project_experience": _render_project_experience,
    "skills": _render_skills,
    "language": _render_language,
    "honors": _render_honors,
    "certificates": _render_certificates,
    "interests": _render_interests,
    "club_activities": _render_club_activities,
    "publications": _render_publications,
    "recommendation": _render_recommendation,
    "social_links": _render_social_links,
    "other": _render_other,
    "custom": _render_custom,
}


def _format_date_range(start: str | None, end: str | None) -> str:
    """格式化日期范围。"""
    if start and end:
        return f"{_esc(start)} - {_esc(end)}"
    if start:
        return f"{_esc(start)} - 至今"
    if end:
        return _esc(end)
    return ""


def render_module(module_type: str, content: dict) -> str:
    """渲染单个模块为 HTML。

    已知 module_type 使用专用渲染器，未知类型走兜底渲染。
    """
    renderer = _MODULE_RENDERERS.get(module_type)
    if renderer is None:
        logger.debug("Unknown module_type '%s', using fallback renderer", module_type)
        return _render_fallback(module_type, content)
    return renderer(content)


# ═══════════════════════════════════════════════════════════
# 主渲染入口
# ═══════════════════════════════════════════════════════════


def render_resume(
    modules: list,
    style: ResumeStyle | None = None,
    filename: str | None = None,
) -> str:
    """渲染简历为完整 HTML 文档。

    Args:
        modules: ResumeModule 列表（需有 module_type, content, sort_order 属性）
        style: 样式配置（None 时用默认 ResumeStyle）
        filename: 简历文件名（用于 <title>）

    Returns:
        完整 HTML 文档字符串（含 CSS 变量已预解析）

    Raises:
        ValueError: template_id 不存在
    """
    if style is None:
        style = ResumeStyle()

    # 1. 获取模板
    template_html = TemplateRegistry.get(style.template_id)

    # 2. 渲染模块（支持双栏/头带模板：{{sidebar}}/{{basic_header}} 占位符分流）
    has_sidebar = "{{sidebar}}" in template_html
    has_basic_header = "{{basic_header}}" in template_html
    # 侧栏模块：基本信息/技能/语言/兴趣/社交链接（双栏布局左侧）
    sidebar_types = {"basic_info", "skills", "language", "social_links", "interests"}
    # 隐藏模块（显隐控制，不渲染不导出）
    hidden_modules = set(style.hidden_modules or [])
    modules_html = []
    sidebar_html = []
    basic_header_html = []
    for mod in sorted(modules, key=lambda m: (getattr(m, "sort_order", 0), getattr(m, "id", 0))):
        if mod.module_type in hidden_modules:
            continue
        content = mod.content if isinstance(mod.content, dict) else {}
        # v2: 检查 metadata.hidden
        meta = content.get("metadata", {})
        if isinstance(meta, dict) and meta.get("hidden"):
            continue
        # v2: 优先使用 metadata.title，兜底 DEFAULT_MODULE_LABELS
        title = get_content_title(content, mod.module_type)
        content_html = render_module(mod.module_type, content)
        if content_html.strip():
            # 头带模板：basic_info 提取为独立头部（深色带），不进 modules
            if has_basic_header and mod.module_type == "basic_info":
                basic_header_html.append(content_html)
                continue
            section = (
                f'<section class="module module-{mod.module_type}">\n'
                f'<h2 class="module-title">{title}</h2>\n'
                f'<div class="module-content">{content_html}</div>\n'
                f"</section>"
            )
            if has_sidebar and mod.module_type in sidebar_types:
                sidebar_html.append(section)
            else:
                modules_html.append(section)

    # 3. 替换模板占位符
    html = template_html.replace("{{modules}}", "\n".join(modules_html))
    if has_sidebar:
        html = html.replace("{{sidebar}}", "\n".join(sidebar_html))
    if has_basic_header:
        html = html.replace("{{basic_header}}", "\n".join(basic_header_html))
    html = html.replace("{{filename}}", _esc(filename or "简历"))

    # 4. 预解析 CSS 变量
    html = preparse_css_variables(html, style)

    # 5. 注入自定义 CSS（在变量预解析之后，追加到 </style> 前）
    if style.custom_css.strip():
        custom_css_block = f"\n  /* custom_css */\n  {style.custom_css.strip()}\n"
        html = html.replace("</style>", f"{custom_css_block}</style>", 1)

    logger.info(
        "Rendered resume: template=%s, modules=%d, size=%d chars",
        style.template_id, len(modules), len(html),
    )
    return html


def render_resume_from_dict(
    modules_data: list[dict],
    style: ResumeStyle | None = None,
    filename: str | None = None,
) -> str:
    """从 dict 列表渲染简历（不需要 ORM 对象）。

    用于 preview / 测试场景，modules_data 格式：
    [{"module_type": "basic_info", "content": {...}, "sort_order": 0}, ...]
    """

    class _Mod:
        def __init__(self, d: dict):
            self.module_type = d["module_type"]
            self.content = d.get("content", {})
            self.sort_order = d.get("sort_order", 0)
            self.id = d.get("id", 0)

    modules = [_Mod(d) for d in modules_data]
    return render_resume(modules, style, filename)
