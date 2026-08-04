"""15 模块 content JSON 字段级 schema — 四方契约单一数据源（v2 统一结构）。

四方消费方：
  - 表单（前端 BuilderPage 表单校验）
  - AI 生成（generate_module / rewrite_resume 工具，LLM 输出 pydantic 校验）
  - 反解析（parse-to-modules 接口，LLM 反解析输出校验）
  - 模板渲染（resume_template.py 渲染器）

v2 设计原则（统一 Agent 编辑器重设计）：
  - 每个模块 = metadata + items[] 的统一结构
  - 每条 item 必须有唯一 id 和可选 hidden 标志
  - 模块标题可编辑，存储在 metadata.title 而非硬编码映射表
  - 向后兼容：旧数据读取时自动迁移（model_validator）
"""

import hashlib
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict, model_validator


# ═══════════════════════════════════════════════════════════
# 0. 迁移辅助函数
# ═══════════════════════════════════════════════════════════


def _make_id(seed: str) -> str:
    """基于内容生成确定性短 ID（前 8 位 hex）。"""
    return hashlib.md5(seed.encode()).hexdigest()[:8]


def _ensure_item_id(item: dict, index: int, prefix: str = "item") -> dict:
    """确保 item 有 id 字段，无则自动生成。"""
    if "id" not in item:
        item["id"] = f"{prefix}_{_make_id(str(item))}_{index}"
    return item


def _migrate_entries_to_items(data: dict, prefix: str) -> dict:
    """旧格式 entries → 新格式 items，补充 id。

    同时处理 dict 和已解析的 Pydantic 对象。
    """
    if "entries" in data and "items" not in data:
        entries = data.pop("entries")
        # 如果 entries 是 Pydantic 对象列表，转为 dict
        if entries and hasattr(entries[0], "model_dump"):
            entries = [e.model_dump() for e in entries]
        data["items"] = [_ensure_item_id(entry, i, prefix) for i, entry in enumerate(entries)]
    return data


def _ensure_metadata(data: dict, default_title: str) -> dict:
    """确保有 metadata 字段。"""
    if "metadata" not in data:
        data["metadata"] = {"title": default_title}
    elif isinstance(data["metadata"], dict) and "title" not in data["metadata"]:
        data["metadata"]["title"] = default_title
    return data


# ═══════════════════════════════════════════════════════════
# 1. ModuleType 枚举（15 个固定值）
# ═══════════════════════════════════════════════════════════


class ModuleType(str, Enum):
    """15 个固定模块类型。"""

    BASIC_INFO = "basic_info"
    EDUCATION = "education"
    WORK_EXPERIENCE = "work_experience"
    PROJECT_EXPERIENCE = "project_experience"
    SKILLS = "skills"
    LANGUAGE = "language"
    HONORS = "honors"
    CERTIFICATES = "certificates"
    INTERESTS = "interests"
    CLUB_ACTIVITIES = "club_activities"
    PUBLICATIONS = "publications"
    RECOMMENDATION = "recommendation"
    SOCIAL_LINKS = "social_links"
    OTHER = "other"
    CUSTOM = "custom"


# 模块类型 → 默认中文标题（前端和渲染器共用）
DEFAULT_MODULE_LABELS: dict[str, str] = {
    "basic_info": "基本信息",
    "education": "教育经历",
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
# 2. 基础类型（v2 统一结构）
# ═══════════════════════════════════════════════════════════


class ModuleMetadata(BaseModel):
    """所有模块共用的元数据。"""

    title: str = Field(..., max_length=50, description="模块标题（用户可编辑）")
    hidden: bool = Field(False, description="模块级隐藏（不渲染、不导出）")


class BaseItem(BaseModel):
    """所有条目的基础字段。"""

    id: str = Field(
        default_factory=lambda: _make_id(str(datetime.now().timestamp())), description="唯一标识"
    )
    hidden: bool = Field(False, description="条目级隐藏")


# ═══════════════════════════════════════════════════════════
# 3. 核心模块 content schema（4 个）
# ═══════════════════════════════════════════════════════════


class CustomField(BaseModel):
    """自定义键值字段。"""

    key: str = Field(..., min_length=1, max_length=50, description="字段名")
    value: str = Field("", max_length=500, description="字段值")


class BasicInfoContent(BaseModel):
    """基本信息模块 — 单值，无 items。

    必填: name
    v2 新增 metadata 字段。
    """

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="基本信息"))
    name: str = Field(..., min_length=1, max_length=50, description="姓名")
    phone: str | None = Field(None, max_length=20, description="手机号")
    email: str | None = Field(None, max_length=100, description="邮箱")
    gender: str | None = Field(None, max_length=10, description="性别")
    age: int | None = Field(None, ge=0, le=150, description="年龄")
    # SmartResume 派生字段对照（services/derived_fields.py）：服务端从经历/教育推导，缺失时补
    work_years: int | None = Field(None, ge=0, le=60, description="工作年限（派生）")
    highest_education: str | None = Field(
        None, max_length=20, description="最高学历（派生，标准档位 key）"
    )
    location: str | None = Field(None, max_length=100, description="所在城市")
    avatar: str | None = Field(None, max_length=500, description="头像 URL")
    job_title: str | None = Field(None, max_length=100, description="求职意向/当前职位")
    summary: str | None = Field(None, max_length=500, description="个人总结")
    status: str | None = Field(None, max_length=50, description="当前状态")
    hometown: str | None = Field(None, max_length=100, description="籍贯")
    homepage_url: str | None = Field(None, max_length=500, description="主页链接")
    github_url: str | None = Field(None, max_length=500, description="GitHub 链接")
    blog_url: str | None = Field(None, max_length=500, description="博客链接")
    custom_fields: list[CustomField] = Field(default_factory=list, description="自定义字段列表")

    @model_validator(mode="before")
    @classmethod
    def _migrate_basic_info(cls, data: dict) -> dict:
        """旧数据迁移：补充 metadata。"""
        return _ensure_metadata(data, "基本信息")


# ═══════════════════════════════════════════════════════════
# 4. 列表模块 content schema（统一 items 结构）
# ═══════════════════════════════════════════════════════════


class EducationItem(BaseItem):
    """教育经历单条。"""

    school: str = Field(..., min_length=1, max_length=100, description="学校名称")
    degree: str | None = Field(None, max_length=20, description="学历")
    major: str | None = Field(None, max_length=100, description="专业")
    start_date: str | None = Field(None, max_length=20, description="开始时间")
    end_date: str | None = Field(None, max_length=20, description="结束时间")
    gpa: float | None = Field(None, ge=0, le=10, description="GPA")
    description: str | None = Field(None, max_length=500, description="补充说明")


class EducationContent(BaseModel):
    """教育经历模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="教育经历"))
    items: list[EducationItem] = Field(default_factory=list, description="教育经历列表")

    @model_validator(mode="before")
    @classmethod
    def _migrate_education(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，补充 metadata。"""
        data = _ensure_metadata(data, "教育经历")
        data = _migrate_entries_to_items(data, "edu")
        return data


class WorkExperienceItem(BaseItem):
    """工作经历单条。"""

    company: str = Field(..., min_length=1, max_length=100, description="公司名称")
    position: str = Field(..., min_length=1, max_length=100, description="职位")
    start_date: str | None = Field(None, max_length=20, description="开始时间")
    end_date: str | None = Field(None, max_length=20, description="结束时间")
    description: str | None = Field(None, max_length=2000, description="工作内容描述")
    achievements: list[str] = Field(default_factory=list, description="主要成就/亮点")


class WorkExperienceContent(BaseModel):
    """工作经历模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="工作经历"))
    items: list[WorkExperienceItem] = Field(default_factory=list, description="工作经历列表")

    @model_validator(mode="before")
    @classmethod
    def _migrate_work(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，补充 metadata。"""
        data = _ensure_metadata(data, "工作经历")
        data = _migrate_entries_to_items(data, "work")
        return data


class SkillItem(BaseItem):
    """技能单条（v2 重设计：独立条目 + 熟练度）。"""

    name: str = Field(..., min_length=1, max_length=50, description="技能名称")
    level: int | None = Field(None, ge=1, le=5, description="熟练度 1-5")
    category: str | None = Field(None, max_length=50, description="所属分类")


class SkillCategory(BaseModel):
    """技能分类（旧格式，用于迁移）。

    旧格式: {categories: [{name: "编程语言", items: ["Python", "Java"]}]}
    迁移到: {items: [{id, name, level, category}]}
    """

    name: str = Field(..., min_length=1, max_length=50, description="分类名称")
    items: list[str] = Field(default_factory=list, description="技能项列表")


class SkillsContent(BaseModel):
    """专业技能模块（v2 重设计：扁平 items + 熟练度）。

    旧格式: {categories: [{name, items: [...]}]}
    新格式: {items: [{id, name, level, category}]}
    """

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="专业技能"))
    items: list[SkillItem] = Field(default_factory=list, description="技能列表")
    show_levels: bool = Field(False, description="是否显示熟练度条")

    @model_validator(mode="before")
    @classmethod
    def _migrate_skills(cls, data: dict) -> dict:
        """旧数据迁移：categories → items，补充 metadata。"""
        data = _ensure_metadata(data, "专业技能")
        if "categories" in data and "items" not in data:
            categories = data.pop("categories")
            # 如果 categories 是 Pydantic 对象列表，转为 dict
            if categories and hasattr(categories[0], "model_dump"):
                categories = [c.model_dump() for c in categories]
            items = []
            for cat in categories:
                if isinstance(cat, dict):
                    cat_name = cat.get("name", "")
                    skill_names = cat.get("items", [])
                else:
                    # Pydantic object
                    cat_name = getattr(cat, "name", "")
                    skill_names = getattr(cat, "items", [])
                for skill_name in skill_names:
                    items.append(
                        {
                            "id": f"skill_{_make_id(skill_name)}",
                            "name": skill_name,
                            "category": cat_name,
                        }
                    )
            data["items"] = items
        return data


class ProjectExperienceItem(BaseItem):
    """项目经历单条。"""

    name: str = Field(..., min_length=1, max_length=100, description="项目名称")
    role: str | None = Field(None, max_length=100, description="担任角色")
    start_date: str | None = Field(None, max_length=20, description="开始时间")
    end_date: str | None = Field(None, max_length=20, description="结束时间")
    url: str | None = Field(None, max_length=500, description="项目链接")
    description: str | None = Field(None, max_length=2000, description="项目描述")
    tech_stack: list[str] = Field(default_factory=list, description="技术栈")


class ProjectExperienceContent(BaseModel):
    """项目经历模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="项目经历"))
    items: list[ProjectExperienceItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_project(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，补充 metadata。"""
        data = _ensure_metadata(data, "项目经历")
        data = _migrate_entries_to_items(data, "proj")
        return data


class LanguageItem(BaseItem):
    """语言能力单条。"""

    name: str = Field(..., min_length=1, max_length=50, description="语言名称")
    proficiency: str | None = Field(None, max_length=50, description="熟练度")
    score: str | None = Field(None, max_length=50, description="成绩/证书")


class LanguageContent(BaseModel):
    """语言能力模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="语言能力"))
    items: list[LanguageItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_language(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，补充 metadata。"""
        data = _ensure_metadata(data, "语言能力")
        data = _migrate_entries_to_items(data, "lang")
        return data


class HonorItem(BaseItem):
    """荣誉奖项单条。"""

    title: str = Field(..., min_length=1, max_length=200, description="奖项名称")
    date: str | None = Field(None, max_length=20, description="获奖时间")
    description: str | None = Field(None, max_length=500, description="补充说明")


class HonorsContent(BaseModel):
    """荣誉奖项模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="荣誉奖项"))
    items: list[HonorItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_honors(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，补充 metadata。"""
        data = _ensure_metadata(data, "荣誉奖项")
        data = _migrate_entries_to_items(data, "honor")
        return data


class CertificateItem(BaseItem):
    """证书单条。"""

    name: str = Field(..., min_length=1, max_length=200, description="证书名称")
    issuer: str | None = Field(None, max_length=100, description="颁发机构")
    date: str | None = Field(None, max_length=20, description="获得时间")
    score: str | None = Field(None, max_length=50, description="成绩")


class CertificatesContent(BaseModel):
    """证书模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="证书"))
    items: list[CertificateItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_certificates(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，补充 metadata。"""
        data = _ensure_metadata(data, "证书")
        data = _migrate_entries_to_items(data, "cert")
        return data


class InterestItem(BaseItem):
    """兴趣爱好单条。"""

    name: str = Field(..., min_length=1, max_length=50, description="兴趣名称")


class InterestsContent(BaseModel):
    """兴趣爱好模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="兴趣爱好"))
    items: list[InterestItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_interests(cls, data: dict) -> dict:
        """旧数据迁移：items: string[] → items: [{id, name}]，补充 metadata。"""
        data = _ensure_metadata(data, "兴趣爱好")
        if "items" in data and data["items"]:
            first = data["items"][0]
            # string list → object list
            if isinstance(first, str):
                raw_items = data["items"]
                data["items"] = [
                    {"id": f"interest_{_make_id(name)}", "name": name} for name in raw_items
                ]
            # Pydantic objects → dict list
            elif hasattr(first, "model_dump"):
                data["items"] = [i.model_dump() for i in data["items"]]
        return data


class ClubActivityItem(BaseItem):
    """社团活动单条。"""

    name: str = Field(..., min_length=1, max_length=100, description="社团/组织名称")
    role: str | None = Field(None, max_length=100, description="担任角色")
    start_date: str | None = Field(None, max_length=20, description="开始时间")
    end_date: str | None = Field(None, max_length=20, description="结束时间")
    description: str | None = Field(None, max_length=500, description="活动描述")


class ClubActivitiesContent(BaseModel):
    """社团活动模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="社团活动"))
    items: list[ClubActivityItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_club(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，补充 metadata。"""
        data = _ensure_metadata(data, "社团活动")
        data = _migrate_entries_to_items(data, "club")
        return data


class PublicationItem(BaseItem):
    """论文/发表单条。"""

    title: str = Field(..., min_length=1, max_length=300, description="论文标题")
    authors: list[str] = Field(default_factory=list, description="作者列表")
    venue: str | None = Field(None, max_length=200, description="发表期刊/会议")
    date: str | None = Field(None, max_length=20, description="发表时间")
    url: str | None = Field(None, max_length=500, description="链接")


class PublicationsContent(BaseModel):
    """发表论文模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="研究成果"))
    items: list[PublicationItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_publications(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，补充 metadata。"""
        data = _ensure_metadata(data, "研究成果")
        data = _migrate_entries_to_items(data, "pub")
        return data


class RecommendationItem(BaseItem):
    """推荐人单条。"""

    name: str = Field(..., min_length=1, max_length=50, description="推荐人姓名")
    title: str | None = Field(None, max_length=100, description="推荐人职位/头衔")
    organization: str | None = Field(None, max_length=100, description="所属组织")
    contact: str | None = Field(None, max_length=50, description="联系方式")
    email: str | None = Field(None, max_length=100, description="邮箱")


class RecommendationContent(BaseModel):
    """推荐人模块 — 列表。"""

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="推荐人"))
    items: list[RecommendationItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_recommendation(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，补充 metadata。"""
        data = _ensure_metadata(data, "推荐人")
        data = _migrate_entries_to_items(data, "rec")
        return data


# ═══════════════════════════════════════════════════════════
# 5. 重设计模块（social_links / other / custom）
# ═══════════════════════════════════════════════════════════


class SocialProfileItem(BaseItem):
    """社交链接单条（v2 重设计：灵活 profile 数组）。"""

    platform: str = Field(..., min_length=1, max_length=50, description="平台名称")
    url: str = Field(..., min_length=1, max_length=500, description="链接地址")
    icon: str | None = Field(None, max_length=50, description="图标标识")


class SocialLinksContent(BaseModel):
    """社交链接模块（v2 重设计：灵活 items 数组）。

    旧格式: {github, linkedin, website, twitter, wechat, others}
    新格式: {items: [{id, platform, url, icon?}]}
    """

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="社交链接"))
    items: list[SocialProfileItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_social_links(cls, data: dict) -> dict:
        """旧数据迁移：固定字段 → items 数组，补充 metadata。"""
        data = _ensure_metadata(data, "社交链接")
        if "items" not in data:
            items = []
            field_map = {
                "github": "GitHub",
                "linkedin": "LinkedIn",
                "website": "个人网站",
                "twitter": "Twitter",
                "wechat": "微信",
            }
            for field, label in field_map.items():
                val = data.pop(field, None)
                if val:
                    items.append(
                        {
                            "id": f"social_{_make_id(field)}",
                            "platform": label,
                            "url": val,
                        }
                    )
            # 旧的 others 字段
            others = data.pop("others", [])
            if others and hasattr(others[0], "model_dump"):
                others = [o.model_dump() for o in others]
            for other in others:
                if isinstance(other, dict) and (other.get("name") or other.get("url")):
                    items.append(
                        {
                            "id": f"social_{_make_id(other.get('name', 'other'))}",
                            "platform": other.get("name", ""),
                            "url": other.get("url", ""),
                        }
                    )
            data["items"] = items
        return data


class OtherContent(BaseModel):
    """其他模块 — 单值。

    用于不属于任何固定模块的补充信息。
    """

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="其他"))
    title: str | None = Field(None, max_length=100, description="段落标题")
    content: str = Field("", max_length=5000, description="内容文本")

    @model_validator(mode="before")
    @classmethod
    def _migrate_other(cls, data: dict) -> dict:
        """旧数据迁移：补充 metadata。"""
        return _ensure_metadata(data, "其他")


class CustomSectionItem(BaseItem):
    """自定义板块单条。"""

    title: str = Field(..., min_length=1, max_length=100, description="板块标题")
    content: str = Field(..., min_length=1, max_length=5000, description="内容文本")


class CustomContent(BaseModel):
    """自定义模块 — 支持多板块（items）与单板块（title+content）向后兼容。

    旧数据: {title, content}（单板块）
    新数据: {items: [{id, title, content}, ...]}（多板块）
    """

    metadata: ModuleMetadata = Field(default_factory=lambda: ModuleMetadata(title="自定义"))
    title: str | None = Field(None, max_length=100, description="模块标题（单板块模式）")
    content: str | None = Field(None, max_length=5000, description="内容文本（单板块模式）")
    items: list[CustomSectionItem] = Field(default_factory=list, description="多板块列表")

    @model_validator(mode="before")
    @classmethod
    def _migrate_custom(cls, data: dict) -> dict:
        """旧数据迁移：entries → items，单板块 → items，补充 metadata。"""
        data = _ensure_metadata(data, "自定义")
        # entries → items
        if "entries" in data and "items" not in data:
            entries = data.pop("entries")
            if entries and hasattr(entries[0], "model_dump"):
                entries = [e.model_dump() for e in entries]
            data["items"] = [_ensure_item_id(entry, i, "custom") for i, entry in enumerate(entries)]
        # 单板块模式 title+content → items
        if not data.get("items") and data.get("title") and data.get("content"):
            data["items"] = [
                {
                    "id": f"custom_{_make_id(data['title'])}",
                    "title": data["title"],
                    "content": data["content"],
                }
            ]
        return data

    @model_validator(mode="after")
    def _require_content(self) -> "CustomContent":
        """确保要么有 items，要么有 title+content。"""
        if not self.items and (not self.title or not self.content):
            raise ValueError("自定义模块需要提供 title+content（单板块）或 items（多板块）")
        return self


# ═══════════════════════════════════════════════════════════
# 6. module_type → content schema 映射表（四方契约核心）
# ═══════════════════════════════════════════════════════════


MODULE_CONTENT_SCHEMAS: dict[ModuleType, type[BaseModel]] = {
    ModuleType.BASIC_INFO: BasicInfoContent,
    ModuleType.EDUCATION: EducationContent,
    ModuleType.WORK_EXPERIENCE: WorkExperienceContent,
    ModuleType.PROJECT_EXPERIENCE: ProjectExperienceContent,
    ModuleType.SKILLS: SkillsContent,
    ModuleType.LANGUAGE: LanguageContent,
    ModuleType.HONORS: HonorsContent,
    ModuleType.CERTIFICATES: CertificatesContent,
    ModuleType.INTERESTS: InterestsContent,
    ModuleType.CLUB_ACTIVITIES: ClubActivitiesContent,
    ModuleType.PUBLICATIONS: PublicationsContent,
    ModuleType.RECOMMENDATION: RecommendationContent,
    ModuleType.SOCIAL_LINKS: SocialLinksContent,
    ModuleType.OTHER: OtherContent,
    ModuleType.CUSTOM: CustomContent,
}


def validate_module_content(module_type: ModuleType | str, content: dict) -> BaseModel:
    """校验 content 是否符合对应 module_type 的 schema。

    四方契约入口：表单提交 / AI 生成 / 反解析 / 模板渲染前均可调用。
    旧数据通过 model_validator 自动迁移到新格式。

    Args:
        module_type: 模块类型（枚举或字符串）
        content: content JSON dict

    Returns:
        校验后的 Pydantic 模型实例（新格式）

    Raises:
        ValueError: module_type 不在 15 枚举中
        pydantic.ValidationError: content 不符合 schema
    """
    if isinstance(module_type, str):
        try:
            module_type = ModuleType(module_type)
        except ValueError:
            raise ValueError(f"未知 module_type: {module_type}，必须是 15 个固定枚举之一")

    schema_class = MODULE_CONTENT_SCHEMAS[module_type]
    return schema_class(**content)


def get_content_items(content: dict | BaseModel) -> list[dict]:
    """从 content 中提取 items 列表（兼容新旧格式）。

    新格式: content.items
    旧格式: content.entries 或 content.categories（skills）
    """
    if isinstance(content, BaseModel):
        content = content.model_dump()
    if "items" in content:
        return content["items"] if isinstance(content["items"], list) else []
    if "entries" in content:
        return content["entries"] if isinstance(content["entries"], list) else []
    if "categories" in content:
        # skills 旧格式：展平为单条列表
        items = []
        for cat in content.get("categories", []):
            for name in cat.get("items", []):
                items.append({"name": name, "category": cat.get("name", "")})
        return items
    return []


def get_content_title(content: dict | BaseModel, module_type: str) -> str:
    """从 content 中提取模块标题（优先 metadata.title，兜底 DEFAULT_MODULE_LABELS）。"""
    if isinstance(content, BaseModel):
        content = content.model_dump()
    meta = content.get("metadata", {})
    if isinstance(meta, dict) and meta.get("title"):
        return meta["title"]
    return DEFAULT_MODULE_LABELS.get(module_type, module_type)


# ═══════════════════════════════════════════════════════════
# 7. ResumeStyle schema
# ═══════════════════════════════════════════════════════════


class ResumeStyle(BaseModel):
    """简历样式配置 — resumes.style JSON 字段 schema。"""

    @classmethod
    def from_db(cls, raw: dict | str | None) -> "ResumeStyle":
        """从数据库读出的 style 字段解析为 ResumeStyle。"""
        import json as _json

        if not raw:
            return cls()
        if isinstance(raw, str):
            try:
                raw = _json.loads(raw)
            except (ValueError, TypeError):
                return cls()
            if not isinstance(raw, dict):
                return cls()
        try:
            return cls(**raw)
        except Exception:
            return cls()

    template_id: str = Field("default", description="模板 ID")
    font_family: str = Field("Noto Sans CJK SC", description="字体族")
    font_size: str = Field("14px", description="正文字号")
    line_height: float = Field(1.6, ge=1.0, le=3.0, description="行高")
    spacing: str = Field("8px", description="模块间距")
    accent_color: str = Field("#2563eb", description="主题色（hex）")
    margin: str = Field("16mm", description="页边距")
    page_size: str = Field("A4", description="页面大小")
    section_spacing: str = Field("16px", description="段落/条目间距")
    custom_css: str = Field("", description="自定义 CSS")
    hidden_modules: list[str] = Field(default_factory=list, description="隐藏的模块类型列表")


# ═══════════════════════════════════════════════════════════
# 8. CRUD schema（支撑 builder API）
# ═══════════════════════════════════════════════════════════


class ResumeModuleCreate(BaseModel):
    """创建模块请求。"""

    module_type: ModuleType
    content: dict = Field(..., description="模块 content JSON")
    sort_order: int = Field(0, ge=0, description="排序序号")


class ResumeModuleUpdate(BaseModel):
    """更新模块请求（部分更新）。"""

    content: dict | None = None
    sort_order: int | None = Field(None, ge=0)


class ResumeModuleResponse(BaseModel):
    """模块响应。"""

    id: int
    resume_id: int
    module_type: ModuleType
    content: dict
    sort_order: int
    created_at: datetime
    # G 可信度控制：fact/inferred/mixed（AI 改写内容来源标注）
    source: str = "fact"

    model_config = ConfigDict(from_attributes=True)


class ResumeModuleListResponse(BaseModel):
    """模块列表响应。"""

    items: list[ResumeModuleResponse]
    total: int


# ═══════════════════════════════════════════════════════════
# 9. Builder API 请求/响应 schema
# ═══════════════════════════════════════════════════════════


class BuilderCreateRequest(BaseModel):
    """POST /resumes/builder 请求体。"""

    filename: str = Field("未命名简历", max_length=255, description="简历文件名")
    modules: list[ResumeModuleCreate] = Field(default_factory=list, description="初始模块列表")
    style: ResumeStyle | None = Field(None, description="样式配置")


class BuilderDraftUpdateRequest(BaseModel):
    """PUT /resumes/{id}?mode=draft 请求体。"""

    filename: str | None = Field(None, max_length=255, description="简历文件名")
    modules: list[ResumeModuleCreate] | None = Field(None, description="全量替换模块列表")
    style: ResumeStyle | None = Field(None, description="样式配置")


class BuilderUpdateRequest(BaseModel):
    """PUT /resumes/{id} 统一请求体。"""

    version: int | None = Field(None, description="乐观锁版本号")
    filename: str | None = Field(None, max_length=255, description="简历文件名")
    modules: list[ResumeModuleCreate] | None = Field(None, description="全量替换模块列表")
    style: ResumeStyle | None = Field(None, description="样式配置")


class BuilderResumeResponse(BaseModel):
    """Builder 简历响应（含模块列表）。"""

    id: int
    filename: str
    status: str
    source: str
    style: dict | None
    version: int
    created_at: datetime
    is_indexed: bool = False
    is_stale: bool = False
    modules_materialized: bool = True
    modules: list[ResumeModuleResponse] = Field(default_factory=list)
    # 多语言版本：语言标注 + family 归属
    language: str | None = None
    family_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ResumeFamilyItem(BaseModel):
    """多语言版本族中的单个版本（GET /resumes/{id}/family 返回项）。"""

    id: int
    filename: str
    language: str | None = None
    created_at: datetime
    source: str


# ═══════════════════════════════════════════════════════════
# 10. 向后兼容别名（旧代码过渡期使用，后续统一迁移到 Item 命名）
# ═══════════════════════════════════════════════════════════

# Entry → Item 别名
EducationEntry = EducationItem
WorkExperienceEntry = WorkExperienceItem
ProjectExperienceEntry = ProjectExperienceItem
# SkillCategory 保留为独立类（旧格式迁移用），不设为 SkillItem 别名
LanguageEntry = LanguageItem
HonorEntry = HonorItem
CertificateEntry = CertificateItem
ClubActivityEntry = ClubActivityItem
PublicationEntry = PublicationItem
RecommendationEntry = RecommendationItem
SocialProfile = SocialProfileItem
