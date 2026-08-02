"""15 模块 content JSON 字段级 schema — 四方契约单一数据源。

四方消费方：
  - 表单（前端 BuilderPage 表单校验）
  - AI 生成（generate_module / rewrite_resume 工具，LLM 输出 pydantic 校验）
  - 反解析（parse-to-modules 接口，LLM 反解析输出校验）
  - 模板渲染（resume_template.py 渲染器）

15 个 module_type 固定枚举（spec 第 278 行）：
  basic_info / education / work_experience / project_experience /
  skills / language / honors / certificates / interests / club_activities /
  publications / recommendation / social_links / other / custom

设计原则：
  - 单值模块（basic_info / social_links / other / custom）→ content = 平铺对象
  - 列表模块（education / work_experience 等）→ content = {entries: [...]}
  - 至少 4 核心模块（basic_info/education/work_experience/skills）字段名/类型/必填 pin 死
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict


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


# ═══════════════════════════════════════════════════════════
# 2. 核心模块 content schema（4 个，字段名/类型/必填 pin 死）
# ═══════════════════════════════════════════════════════════


class CustomField(BaseModel):
    """自定义键值字段（#6：基本信息等模块支持预设字段之外的自定义项）。"""

    key: str = Field(..., min_length=1, max_length=50, description="字段名")
    value: str = Field("", max_length=500, description="字段值")


class BasicInfoContent(BaseModel):
    """基本信息模块 — 单值，平铺。

    必填: name
    其余可选，表单/AI/反解析/渲染四方一致。
    扩展字段（UP 简历对齐）：status/hometown/homepage_url/github_url/blog_url
    custom_fields: 预设字段之外的自定义键值对（#6）。
    """

    name: str = Field(..., min_length=1, max_length=50, description="姓名")
    phone: str | None = Field(None, max_length=20, description="手机号")
    email: str | None = Field(None, max_length=100, description="邮箱")
    gender: str | None = Field(None, max_length=10, description="性别")
    age: int | None = Field(None, ge=0, le=150, description="年龄")
    location: str | None = Field(None, max_length=100, description="所在城市")
    avatar: str | None = Field(None, max_length=500, description="头像 URL")
    job_title: str | None = Field(None, max_length=100, description="求职意向/当前职位")
    summary: str | None = Field(None, max_length=500, description="个人总结")
    # UP 简历对齐扩展字段
    status: str | None = Field(None, max_length=50, description="当前状态（如 在校生/求职中）")
    hometown: str | None = Field(None, max_length=100, description="籍贯")
    homepage_url: str | None = Field(None, max_length=500, description="主页链接")
    github_url: str | None = Field(None, max_length=500, description="GitHub 链接")
    blog_url: str | None = Field(None, max_length=500, description="博客链接")
    custom_fields: list[CustomField] = Field(default_factory=list, description="自定义字段列表")


class EducationEntry(BaseModel):
    """教育经历单条。"""

    school: str = Field(..., min_length=1, max_length=100, description="学校名称")
    degree: str | None = Field(None, max_length=20, description="学历（大专/本科/硕士/博士）")
    major: str | None = Field(None, max_length=100, description="专业")
    start_date: str | None = Field(None, max_length=20, description="开始时间（如 2021-09）")
    end_date: str | None = Field(None, max_length=20, description="结束时间（如 2025-06 或 至今）")
    gpa: float | None = Field(None, ge=0, le=10, description="GPA")
    description: str | None = Field(None, max_length=500, description="补充说明")


class EducationContent(BaseModel):
    """教育经历模块 — 列表。"""

    entries: list[EducationEntry] = Field(default_factory=list, description="教育经历列表")


class WorkExperienceEntry(BaseModel):
    """工作经历单条。"""

    company: str = Field(..., min_length=1, max_length=100, description="公司名称")
    position: str = Field(..., min_length=1, max_length=100, description="职位")
    start_date: str | None = Field(None, max_length=20, description="开始时间")
    end_date: str | None = Field(None, max_length=20, description="结束时间")
    description: str | None = Field(None, max_length=2000, description="工作内容描述")
    achievements: list[str] = Field(default_factory=list, description="主要成就/亮点")


class WorkExperienceContent(BaseModel):
    """工作经历模块 — 列表。"""

    entries: list[WorkExperienceEntry] = Field(default_factory=list, description="工作经历列表")


class SkillCategory(BaseModel):
    """技能分类单条。"""

    name: str = Field(..., min_length=1, max_length=50, description="分类名称（如 编程语言）")
    items: list[str] = Field(default_factory=list, description="技能项列表")


class SkillsContent(BaseModel):
    """专业技能模块 — 分类列表。

    支持两种模式：
    1. 分类: {categories: [{name: "编程语言", items: ["Python", "Java"]}]}
    2. 扁平: {categories: [{name: "其他", items: ["Python", "FastAPI"]}]}
    """

    categories: list[SkillCategory] = Field(default_factory=list, description="技能分类列表")


# ═══════════════════════════════════════════════════════════
# 3. 其余 11 模块 content schema
# ═══════════════════════════════════════════════════════════


class ProjectExperienceEntry(BaseModel):
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

    entries: list[ProjectExperienceEntry] = Field(default_factory=list)


class LanguageEntry(BaseModel):
    """语言能力单条。"""

    name: str = Field(..., min_length=1, max_length=50, description="语言名称（如 英语）")
    proficiency: str | None = Field(None, max_length=50, description="熟练度（如 流利/一般/CET-6）")
    score: str | None = Field(None, max_length=50, description="成绩/证书")


class LanguageContent(BaseModel):
    """语言能力模块 — 列表。"""

    entries: list[LanguageEntry] = Field(default_factory=list)


class HonorEntry(BaseModel):
    """荣誉奖项单条。"""

    title: str = Field(..., min_length=1, max_length=200, description="奖项名称")
    date: str | None = Field(None, max_length=20, description="获奖时间")
    description: str | None = Field(None, max_length=500, description="补充说明")


class HonorsContent(BaseModel):
    """荣誉奖项模块 — 列表。"""

    entries: list[HonorEntry] = Field(default_factory=list)


class CertificateEntry(BaseModel):
    """证书单条。"""

    name: str = Field(..., min_length=1, max_length=200, description="证书名称")
    issuer: str | None = Field(None, max_length=100, description="颁发机构")
    date: str | None = Field(None, max_length=20, description="获得时间")
    score: str | None = Field(None, max_length=50, description="成绩")


class CertificatesContent(BaseModel):
    """证书模块 — 列表。"""

    entries: list[CertificateEntry] = Field(default_factory=list)


class InterestsContent(BaseModel):
    """兴趣爱好模块 — 扁平字符串列表。"""

    items: list[str] = Field(default_factory=list, description="兴趣列表")


class ClubActivityEntry(BaseModel):
    """社团活动单条。"""

    name: str = Field(..., min_length=1, max_length=100, description="社团/组织名称")
    role: str | None = Field(None, max_length=100, description="担任角色")
    start_date: str | None = Field(None, max_length=20, description="开始时间")
    end_date: str | None = Field(None, max_length=20, description="结束时间")
    description: str | None = Field(None, max_length=500, description="活动描述")


class ClubActivitiesContent(BaseModel):
    """社团活动模块 — 列表。"""

    entries: list[ClubActivityEntry] = Field(default_factory=list)


class PublicationEntry(BaseModel):
    """论文/发表单条。"""

    title: str = Field(..., min_length=1, max_length=300, description="论文标题")
    authors: list[str] = Field(default_factory=list, description="作者列表")
    venue: str | None = Field(None, max_length=200, description="发表期刊/会议")
    date: str | None = Field(None, max_length=20, description="发表时间")
    url: str | None = Field(None, max_length=500, description="链接")


class PublicationsContent(BaseModel):
    """发表论文模块 — 列表。"""

    entries: list[PublicationEntry] = Field(default_factory=list)


class RecommendationEntry(BaseModel):
    """推荐人单条。"""

    name: str = Field(..., min_length=1, max_length=50, description="推荐人姓名")
    title: str | None = Field(None, max_length=100, description="推荐人职位/头衔")
    organization: str | None = Field(None, max_length=100, description="所属组织")
    contact: str | None = Field(None, max_length=50, description="联系方式")
    email: str | None = Field(None, max_length=100, description="邮箱")


class RecommendationContent(BaseModel):
    """推荐人模块 — 列表。"""

    entries: list[RecommendationEntry] = Field(default_factory=list)


class SocialLinksContent(BaseModel):
    """社交链接模块 — 单值，平铺。"""

    github: str | None = Field(None, max_length=500, description="GitHub 主页")
    linkedin: str | None = Field(None, max_length=500, description="LinkedIn 主页")
    website: str | None = Field(None, max_length=500, description="个人网站")
    twitter: str | None = Field(None, max_length=500, description="Twitter/X")
    wechat: str | None = Field(None, max_length=100, description="微信号")
    others: list[dict] = Field(default_factory=list, description="其他链接 [{name, url}]")


class OtherContent(BaseModel):
    """其他模块 — 单值。

    用于不属于任何固定模块的补充信息。
    """

    title: str | None = Field(None, max_length=100, description="段落标题")
    content: str = Field(..., min_length=1, max_length=5000, description="内容文本")


class CustomContent(BaseModel):
    """自定义模块 — 单值。

    模板渲染器对此类型有兜底分支（spec 第 228 行）。
    """

    title: str = Field(..., min_length=1, max_length=100, description="模块标题")
    content: str = Field(..., min_length=1, max_length=5000, description="内容文本")


# ═══════════════════════════════════════════════════════════
# 4. module_type → content schema 映射表（四方契约核心）
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

    Args:
        module_type: 模块类型（枚举或字符串）
        content: content JSON dict

    Returns:
        校验后的 Pydantic 模型实例

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


# ═══════════════════════════════════════════════════════════
# 5. ResumeStyle schema（spec 第 270 行）
# ═══════════════════════════════════════════════════════════


class ResumeStyle(BaseModel):
    """简历样式配置 — resumes.style JSON 字段 schema。

    spec 第 270 行：{template_id, font_family, font_size, line_height, spacing, accent_color}
    扩展字段：margin, page_size, section_spacing, custom_css（向后兼容，全部带默认值）
    """

    @classmethod
    def from_db(cls, raw: dict | str | None) -> "ResumeStyle":
        """从数据库读出的 style 字段解析为 ResumeStyle。

        历史脏数据把 style 双重序列化为 JSON 字符串（如
        '"{\\"margin\\": \\"13mm\\", ...}"'），SQLAlchemy JSON 列读出来是 str 而非 dict，
        `ResumeStyle(**str)` 会抛 TypeError。此方法做防御性解析：

        - None / 空 → 默认样式
        - dict → 直接校验
        - str → json.loads 后再校验；解析失败回退默认样式
        """
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
            # 字段值非法（如 line_height 超界）时回退默认，避免渲染整条链路 500
            return cls()

    template_id: str = Field("default", description="模板 ID（default/minimal/business）")
    font_family: str = Field("Noto Sans CJK SC", description="字体族")
    font_size: str = Field("14px", description="正文字号")
    line_height: float = Field(1.6, ge=1.0, le=3.0, description="行高")
    spacing: str = Field("8px", description="模块间距")
    accent_color: str = Field("#2563eb", description="主题色（hex）")
    margin: str = Field("16mm", description="页边距（如 16mm / 20px）")
    page_size: str = Field("A4", description="页面大小（A4 / Letter）")
    section_spacing: str = Field("16px", description="段落/条目间距")
    custom_css: str = Field("", description="自定义 CSS（渲染时追加到样式末尾）")


# ═══════════════════════════════════════════════════════════
# 6. CRUD schema（支撑 builder API）
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

    model_config = ConfigDict(from_attributes=True)


class ResumeModuleListResponse(BaseModel):
    """模块列表响应。"""

    items: list[ResumeModuleResponse]
    total: int


# ═══════════════════════════════════════════════════════════
# 7. Builder API 请求/响应 schema（T23）
# ═══════════════════════════════════════════════════════════


class BuilderCreateRequest(BaseModel):
    """POST /resumes/builder 请求体。

    新建 builder 简历 + 初始模块列表（可选）。
    spec F 端点第 258 行。
    """

    filename: str = Field("未命名简历", max_length=255, description="简历文件名")
    modules: list[ResumeModuleCreate] = Field(default_factory=list, description="初始模块列表")
    style: ResumeStyle | None = Field(None, description="样式配置")


class BuilderDraftUpdateRequest(BaseModel):
    """PUT /resumes/{id}?mode=draft 请求体。

    草稿模式 last-write-wins（spec A5#66）：
    - modules: 全量替换（前端传当前所有模块）
    - style / filename: 可选部分更新
    - 不查 version，不 bump version
    """

    filename: str | None = Field(None, max_length=255, description="简历文件名")
    modules: list[ResumeModuleCreate] | None = Field(None, description="全量替换模块列表")
    style: ResumeStyle | None = Field(None, description="样式配置")


class BuilderUpdateRequest(BaseModel):
    """PUT /resumes/{id} 统一请求体（draft 和 complete 共用）。

    - mode=draft: version 字段忽略（last-write-wins，spec A5#66）
    - mode=complete: version 必填（乐观锁，spec F 端点）
    """

    version: int | None = Field(None, description="乐观锁版本号（mode=complete 时必填）")
    filename: str | None = Field(None, max_length=255, description="简历文件名")
    modules: list[ResumeModuleCreate] | None = Field(None, description="全量替换模块列表")
    style: ResumeStyle | None = Field(None, description="样式配置")


class BuilderResumeResponse(BaseModel):
    """Builder 简历响应（含模块列表）。

    POST /resumes/builder 和 PUT /resumes/{id} 共用。
    """

    id: int
    filename: str
    status: str
    source: str
    style: dict | None
    version: int
    created_at: datetime
    # T17 渲染优化：索引新鲜度并入 builder 响应，避免前端再拉一次 getResume
    is_indexed: bool = False
    is_stale: bool = False
    modules: list[ResumeModuleResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
