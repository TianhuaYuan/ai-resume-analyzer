"""简历派生字段（直接复制 SmartResume smartresume/data/data_processor.py 对应函数，Apache-2.0）。

纯函数、零依赖：从 materialize 后的简历模块派生工作年限/最高学历/年龄/GPA，
并做公司/校名清洗——供匹配、展示、分析统一消费（SmartResume 派生字段契约对照）。

各函数与 SmartResume 原始实现的对应：
- derive_work_years      ← _calculate_work_years（L736-766：跳过实习 → 最早工作起始年，回退最新毕业年）
- derive_highest_education ← _extract_highest_education（L795-844：最近 startDate 优先 + 学历优先级表）
- extract_age            ← _extract_age_number
- extract_gpa            ← _extract_gpa_number
- clean_company_name     ← _clean_company_name
- clean_school_name      ← _clean_school_name
"""

import re
from datetime import datetime

# 学历优先级（值越小越高，对齐 SmartResume education_priority L800-804）
EDUCATION_PRIORITY: dict[str, int] = {
    "DOCTOR": 1,
    "MASTER": 2,
    "BACHELOR": 3,
    "ASSOCIATE": 4,
    "VOCATIONAL_SECONDARY": 5,
    "HIGH_SCHOOL": 6,
    "JUNIOR_HIGH_SCHOOL": 7,
    "PRIMARY_SCHOOL": 8,
}

# 学历关键词表（对齐 SmartResume education_keywords L805-818）
EDUCATION_KEYWORDS: dict[str, list[str]] = {
    "DOCTOR": ["博士", "phd", "doctor", "博士研究生"],
    "MASTER": ["硕士", "研究生", "master", "硕士研究生"],
    "BACHELOR": ["本科", "bachelor", "学士", "本科生"],
    "ASSOCIATE": ["专科", "大专", "associate", "专科生"],
    "VOCATIONAL_SECONDARY": [
        "中专",
        "中等专业学校",
        "vocational high school",
        "secondary vocational school",
    ],
    "HIGH_SCHOOL": ["高中", "high", "高级中学", "中学"],
    "JUNIOR_HIGH_SCHOOL": ["初中", "初级中学"],
    "PRIMARY_SCHOOL": ["小学", "初等教育"],
}


def _extract_year(date_text: str | None) -> int | None:
    """从 "2024-09" / "2024年9月" / "2024.3" 等格式提取年份。"""
    if not date_text or not str(date_text).strip():
        return None
    m = re.search(r"(19|20)\d{2}", str(date_text))
    return int(m.group(0)) if m else None


def derive_work_years(
    work_items: list[dict], edu_items: list[dict], current_year: int | None = None
) -> int:
    """工作年限：最早非实习工作起始年 → 回退最新毕业年（SmartResume _calculate_work_years）。

    Args:
        work_items: work_experience 模块 items（start_date/end_date/internship）
        edu_items: education 模块 items（start_date/end_date）
        current_year: 测试注入用（默认今年）

    Returns:
        工作年限；无法推导返回 -1。
    """
    now = current_year or datetime.now().year
    earliest_work_year = None
    for work in work_items or []:
        if work.get("internship") == 1:
            continue
        y = _extract_year(work.get("start_date"))
        if y is not None and (earliest_work_year is None or y < earliest_work_year):
            earliest_work_year = y
    if earliest_work_year is not None:
        return now - earliest_work_year

    latest_graduation_year = None
    for edu in edu_items or []:
        end = str(edu.get("end_date") or "").strip()
        if end and end not in ("至今", "present", "现在", "目前"):
            y = _extract_year(end)
            if y is not None and (latest_graduation_year is None or y > latest_graduation_year):
                latest_graduation_year = y
    if latest_graduation_year is not None:
        return now - latest_graduation_year
    return -1


def _standardize_education_level(degree_text: str) -> str:
    """学历文本 → 标准档位 key（SmartResume _standardize_education_level 对照）。"""
    if not degree_text:
        return ""
    dl = str(degree_text).lower().strip()
    for standard, keywords in EDUCATION_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in dl:
                return standard
    return ""


def derive_highest_education(edu_items: list[dict]) -> str:
    """最高学历：最近 startDate 优先，学历优先级表兜底（SmartResume _extract_highest_education）。

    Returns:
        标准档位 key（DOCTOR/MASTER/BACHELOR/...）；无法推导返回 ""。
    """
    educations = edu_items or []
    if not educations:
        return ""

    latest_education = None
    latest_year = None
    for edu in educations:
        y = _extract_year(edu.get("start_date"))
        if y is not None and (latest_year is None or y > latest_year):
            latest_year = y
            latest_education = edu
    if latest_education:
        std = _standardize_education_level(latest_education.get("degree", ""))
        if std:
            return std

    best_priority = 999
    result = ""
    for edu in educations:
        std = _standardize_education_level(edu.get("degree", ""))
        if std:
            p = EDUCATION_PRIORITY.get(std, 999)
            if p < best_priority:
                best_priority = p
                result = std
    return result


def extract_age(age_text: str | int | None) -> int:
    """年龄提取（16-99 校验，SmartResume _extract_age_number）。无法提取返回 -1。"""
    if age_text is None:
        return -1
    m = re.search(r"(\d+)", str(age_text))
    if m:
        try:
            age = int(m.group(1))
            if 16 <= age <= 99:
                return age
        except ValueError:
            pass
    return -1


def extract_gpa(gpa_text: str | float | None) -> float:
    """GPA 提取（取最小数、0-5 校验，SmartResume _extract_gpa_number）。无法提取返回 -1.0。"""
    if gpa_text is None:
        return -1.0
    numbers = [float(m) for m in re.findall(r"(\d+\.?\d*)", str(gpa_text))]
    if numbers:
        min_gpa = min(numbers)
        if 0.0 <= min_gpa <= 5.0:
            return min_gpa
    return -1.0


def clean_company_name(company: str | None) -> str:
    """公司名清洗：重复后缀折叠（SmartResume _clean_company_name）。"""
    if not company:
        return ""
    company = str(company).strip()
    for suffix in ("有限公司", "股份有限公司", "科技有限公司", "网络科技有限公司"):
        count = company.count(suffix)
        if count > 1:
            company = company.replace(suffix, "", count - 1)
    return company


def clean_school_name(school: str | None) -> str:
    """校名清洗：去括号及括号内容（SmartResume _clean_school_name）。"""
    if not school:
        return ""
    school = str(school).strip()
    school = re.sub(r"\([^)]*\)", "", school)
    school = re.sub(r"（[^）]*）", "", school)
    return school.strip()
