"""范文结构化模块生成 — 把范文 content 分节文本解析为 builder modules + style。

背景：范文页"快速套用结构"需要 payload.modules（结构化简历模块）+ payload.style。
范文同步时 content 是 `## 个人总结/工作经历/项目经历/教育背景/技能` 分节的自由文本，
本模块用启发式解析为 builder 模块（全部符合 schemas.resume_module schema）。

设计原则：
- 启发式尽力解析，单块解析失败跳过该块；整体异常降级 modules=[]（前端走 AI 改写）
- 合规：name 用占位"示例姓名"，不取范文原文姓名；响应不含 content 原文
"""

import logging
import re

from schemas.resume_module import (
    BasicInfoContent,
    EducationContent,
    EducationEntry,
    ProjectExperienceContent,
    ProjectExperienceEntry,
    ResumeStyle,
    SkillCategory,
    SkillsContent,
    WorkExperienceContent,
    WorkExperienceEntry,
)

logger = logging.getLogger(__name__)

# 匹配 "2021-2025" / "2021.09-2025.06" / "2021年9月-至今" / "2021.09 至 2025.06" 等
_DATE_RE = re.compile(
    r"((?:19|20)\d{2})[-/.年]?(\d{1,2})?月?\s*[-至到~—]\s*"
    r"((?:19|20)\d{2})?[-/.年]?(\d{1,2})?月?"
)
_DEGREE_ORDER = ("博士", "硕士", "本科", "大专")


def _clip(text: str | None, max_len: int) -> str | None:
    """截断文本（None 或空返回 None）。"""
    if not text:
        return None
    text = text.strip()
    return text[:max_len] if text else None


def _clip_items(items: list[str]) -> list[str]:
    """技能项去重 + 截断。"""
    seen: list[str] = []
    for x in items:
        x = x.strip()
        if x and x not in seen and len(x) <= 50:
            seen.append(x)
        if len(seen) >= 20:
            break
    return seen


def _split_sections(content: str) -> dict[str, str]:
    """按 `## 标题` 分节。"""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current:
                sections[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections


def _parse_period(text: str) -> tuple[str | None, str | None]:
    """提取起止时间。返回 (start, end)，end 可能为 '至今'。"""
    m = _DATE_RE.search(text or "")
    if not m:
        return None, None
    start = m.group(1)
    if m.group(2):
        start += "-" + m.group(2).zfill(2)
    if m.group(3):
        end = m.group(3)
        if m.group(4):
            end += "-" + m.group(4).zfill(2)
    else:
        end = "至今" if re.search(r"至今|现在", (text or "")[m.end():m.end() + 8]) else None
    return start, end


def _extract_degree(text: str) -> str | None:
    for d in _DEGREE_ORDER:
        if d in (text or ""):
            return d
    return None


def _parse_education(text: str) -> EducationContent:
    entries: list[EducationEntry] = []
    for block in re.split(r"\n\s*\n", text or ""):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        school = _clip(lines[0], 100) or "示例大学"
        degree = _extract_degree(block)
        major = None
        for ln in lines[1:]:
            if "专业" in ln or "|" in ln or "｜" in ln:
                parts = re.split(r"[|｜·]", ln)
                major = _clip(parts[-1].replace("专业", "").strip(), 100) or major
                break
        start, end = _parse_period(block)
        entries.append(
            EducationEntry(
                school=school,
                degree=degree,
                major=major,
                start_date=start,
                end_date=end,
                description=_clip(block, 500),
            )
        )
    return EducationContent(entries=entries[:5])


def _parse_work(text: str) -> WorkExperienceContent:
    entries: list[WorkExperienceEntry] = []
    for block in re.split(r"\n\s*\n", text or ""):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        first = lines[0]
        company = position = None
        if re.search(r"\s*[-—–]\s*", first):
            parts = re.split(r"\s*[-—–]\s*", first, maxsplit=1)
            if len(parts) == 2:
                company, position = parts[0].strip(), parts[1].strip()
        elif "@" in first:
            pos, _, comp = first.partition("@")
            position, company = pos.strip(), comp.strip()
        else:
            company = first
        if not company and not position:
            continue
        start, end = _parse_period(block)
        desc_lines = lines[1:]
        entries.append(
            WorkExperienceEntry(
                company=_clip(company, 100) or "示例公司",
                position=_clip(position, 100) or "示例职位",
                start_date=start,
                end_date=end,
                description=_clip("\n".join(desc_lines), 2000) if desc_lines else None,
            )
        )
    return WorkExperienceContent(entries=entries[:6])


def _parse_projects(text: str) -> ProjectExperienceContent:
    entries: list[ProjectExperienceEntry] = []
    for block in re.split(r"\n\s*\n", text or ""):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        name = _clip(lines[0], 100)
        if not name:
            continue
        role = None
        tech_stack: list[str] = []
        desc_lines: list[str] = []
        for ln in lines[1:]:
            if "技术" in ln and re.search(r"[:：]", ln):
                ts = re.split(r"[:：]", ln, maxsplit=1)[-1]
                tech_stack = _clip_items(re.split(r"[\s,，、;；]+", ts))
            elif re.search(r"担任|角色", ln):
                role = _clip(ln.split(":")[-1].split("：")[-1].strip(), 100)
            else:
                desc_lines.append(ln)
        start, end = _parse_period(block)
        entries.append(
            ProjectExperienceEntry(
                name=name,
                role=role,
                start_date=start,
                end_date=end,
                description=_clip("\n".join(desc_lines), 2000) if desc_lines else None,
                tech_stack=tech_stack,
            )
        )
    return ProjectExperienceContent(entries=entries[:6])


def _parse_skills(text: str) -> SkillsContent:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return SkillsContent(categories=[])
    categories: list[SkillCategory] = []
    current_name: str | None = None
    current_items: list[str] = []
    for ln in lines:
        # 短行且无分隔符 → 视为分类名
        if len(ln) <= 8 and not re.search(r"[,，、;；\s]", ln):
            if current_name or current_items:
                categories.append(SkillCategory(name=current_name or "其他", items=_clip_items(current_items)))
            current_name = ln
            current_items = []
        else:
            current_items.extend(x for x in re.split(r"[,，、;；\s]+", ln) if x.strip())
    if current_name or current_items:
        categories.append(SkillCategory(name=current_name or "其他", items=_clip_items(current_items)))
    return SkillsContent(categories=categories[:6])


def _pick_style(target_position: str | None) -> ResumeStyle:
    """按目标岗位确定性选模板。"""
    t = target_position or ""
    if any(k in t for k in ("算法", "开发", "工程师", "嵌入式", "技术")):
        return ResumeStyle(template_id="professional")
    if any(k in t for k in ("设计", "视觉", "UI", "UX")):
        return ResumeStyle(template_id="editorial")
    return ResumeStyle(template_id="default")


def build_sample_payload(content: str, payload: dict | None) -> dict:
    """从范文 content 生成完整 payload（含 style + modules）。

    任何异常降级 modules=[]（前端自动走"仅支持 AI 改写"路径，不阻断浏览）。
    """
    base = dict(payload or {})
    target_position = base.get("target_position") or ""
    try:
        sections = _split_sections(content or "")
        if not any(sections.values()):
            base["modules"] = []
            base["style"] = _pick_style(target_position).model_dump()
            return base

        modules: list[dict] = []
        order = 0
        basic = BasicInfoContent(
            name="示例姓名",
            job_title=_clip(target_position, 100) or None,
            summary=_clip(sections.get("个人总结", ""), 500),
        )
        modules.append({"module_type": "basic_info", "content": basic.model_dump(), "sort_order": order})
        order += 1

        edu = _parse_education(sections.get("教育背景", ""))
        if edu.entries:
            modules.append({"module_type": "education", "content": edu.model_dump(), "sort_order": order})
            order += 1
        work = _parse_work(sections.get("工作经历", ""))
        if work.entries:
            modules.append({"module_type": "work_experience", "content": work.model_dump(), "sort_order": order})
            order += 1
        proj = _parse_projects(sections.get("项目经历", ""))
        if proj.entries:
            modules.append({"module_type": "project_experience", "content": proj.model_dump(), "sort_order": order})
            order += 1
        skills = _parse_skills(sections.get("技能", ""))
        if skills.categories:
            modules.append({"module_type": "skills", "content": skills.model_dump(), "sort_order": order})

        base["style"] = _pick_style(target_position).model_dump()
        base["modules"] = modules
    except Exception:  # noqa: BLE001 范文解析不阻断浏览
        logger.exception("sample payload build failed")
        base.setdefault("style", {})
        base["modules"] = []
    return base
