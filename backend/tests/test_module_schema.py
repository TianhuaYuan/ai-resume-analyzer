"""15 模块 schema pin 测试。

验证 schemas/resume_module.py 的：
1. ModuleType 枚举完整性（15 个值）
2. MODULE_CONTENT_SCHEMAS 映射表覆盖全部 15 类型
3. 4 核心模块 content schema 字段名/类型/必填校验
4. 11 非核心模块 content schema 基本校验
5. validate_module_content 函数（字符串/枚举入参 + 未知类型 + 校验失败）
6. ResumeStyle 默认值 + 自定义
7. CRUD schema 序列化/反序列化
"""

import pytest
from pydantic import ValidationError

from schemas.resume_module import (
    MODULE_CONTENT_SCHEMAS,
    ModuleType,
    ResumeModuleCreate,
    ResumeModuleListResponse,
    ResumeModuleResponse,
    ResumeModuleUpdate,
    ResumeStyle,
    validate_module_content,
    BasicInfoContent,
    EducationContent,
    EducationEntry,
    WorkExperienceContent,
    WorkExperienceEntry,
    SkillsContent,
    SkillCategory,
    SkillItem,
    ProjectExperienceContent,
    LanguageContent,
    HonorsContent,
    CertificatesContent,
    InterestsContent,
    ClubActivitiesContent,
    PublicationsContent,
    RecommendationContent,
    SocialLinksContent,
    OtherContent,
    CustomContent,
)


# ═══════════════════════════════════════════════════════════════
# 1. ModuleType 枚举完整性
# ═══════════════════════════════════════════════════════════════


class TestModuleTypeEnum:
    """ModuleType 枚举 15 个固定值。"""

    def test_enum_has_fifteen_values(self):
        """枚举恰好 15 个值。"""
        assert len(ModuleType) == 15

    def test_all_expected_values_present(self):
        """15 个固定 module_type 全部存在。"""
        expected = {
            "basic_info", "education", "work_experience", "project_experience",
            "skills", "language", "honors", "certificates", "interests",
            "club_activities", "publications", "recommendation",
            "social_links", "other", "custom",
        }
        actual = {member.value for member in ModuleType}
        assert actual == expected

    def test_enum_is_str_subclass(self):
        """枚举继承 str，可直接序列化为 JSON 字符串。"""
        assert isinstance(ModuleType.BASIC_INFO, str)
        assert ModuleType.BASIC_INFO == "basic_info"

    def test_enum_from_string(self):
        """字符串可构造枚举。"""
        assert ModuleType("education") == ModuleType.EDUCATION

    def test_unknown_string_raises_value_error(self):
        """未知字符串构造枚举报错。"""
        with pytest.raises(ValueError):
            ModuleType("unknown_type")


# ═══════════════════════════════════════════════════════════════
# 2. MODULE_CONTENT_SCHEMAS 映射表
# ═══════════════════════════════════════════════════════════════


class TestModuleContentSchemasMap:
    """module_type → content schema 映射表覆盖全部 15 类型。"""

    def test_map_covers_all_fifteen_types(self):
        """映射表覆盖全部 15 个 ModuleType。"""
        assert set(MODULE_CONTENT_SCHEMAS.keys()) == set(ModuleType)

    def test_each_value_is_basemodel_subclass(self):
        """映射表每个值都是 Pydantic BaseModel 子类。"""
        from pydantic import BaseModel
        for schema_class in MODULE_CONTENT_SCHEMAS.values():
            assert issubclass(schema_class, BaseModel)


# ═══════════════════════════════════════════════════════════════
# 3. 4 核心模块 content schema 校验
# ═══════════════════════════════════════════════════════════════


class TestBasicInfoContent:
    """基本信息模块 — name 必填，其余可选。"""

    def test_valid_with_name_only(self):
        """仅 name 即可创建。"""
        obj = BasicInfoContent(name="张三")
        assert obj.name == "张三"
        assert obj.phone is None

    def test_valid_with_all_fields(self):
        """全字段创建。"""
        obj = BasicInfoContent(
            name="张三", phone="13800138000", email="test@test.com",
            gender="男", age=25, location="广州",
            avatar="https://example.com/a.png",
            job_title="Python 后端工程师", summary="3 年开发经验",
        )
        assert obj.name == "张三"
        assert obj.age == 25

    def test_name_required(self):
        """缺少 name 报错。"""
        with pytest.raises(ValidationError):
            BasicInfoContent()

    def test_name_empty_string_rejected(self):
        """空字符串 name 被拒（min_length=1）。"""
        with pytest.raises(ValidationError):
            BasicInfoContent(name="")

    def test_age_out_of_range_rejected(self):
        """age 超范围被拒。"""
        with pytest.raises(ValidationError):
            BasicInfoContent(name="张三", age=200)
        with pytest.raises(ValidationError):
            BasicInfoContent(name="张三", age=-1)


class TestEducationContent:
    """教育经历模块 — items 列表（v2 统一结构）。"""

    def test_empty_items_default(self):
        """默认空列表。"""
        obj = EducationContent()
        assert obj.items == []

    def test_valid_entry(self):
        """有效教育经历（使用旧 entries 格式自动迁移）。"""
        obj = EducationContent(entries=[
            EducationEntry(school="广东海洋大学", degree="本科", major="软件工程",
                          start_date="2023-09", end_date="2027-06"),
        ])
        assert obj.items[0].school == "广东海洋大学"

    def test_valid_entry_new_format(self):
        """有效教育经历（使用新 items 格式）。"""
        obj = EducationContent(items=[
            EducationEntry(school="广东海洋大学", degree="本科", major="软件工程"),
        ])
        assert obj.items[0].school == "广东海洋大学"

    def test_entry_school_required(self):
        """education entry 缺少 school 报错。"""
        with pytest.raises(ValidationError):
            EducationEntry(degree="本科")

    def test_gpa_out_of_range_rejected(self):
        """GPA 超范围被拒。"""
        with pytest.raises(ValidationError):
            EducationEntry(school="test", gpa=11.0)

    def test_multiple_entries(self):
        """多条教育经历。"""
        obj = EducationContent(entries=[
            EducationEntry(school="A 大学"),
            EducationEntry(school="B 大学"),
        ])
        assert len(obj.items) == 2


class TestWorkExperienceContent:
    """工作经历模块 — company + position 必填。"""

    def test_valid_entry(self):
        """有效工作经历（使用旧 entries 格式自动迁移）。"""
        obj = WorkExperienceContent(entries=[
            WorkExperienceEntry(
                company="字节跳动", position="后端开发",
                start_date="2024-01", end_date="至今",
                description="负责 API 开发",
                achievements=["优化接口性能 50%", "主导微服务拆分"],
            ),
        ])
        assert obj.items[0].company == "字节跳动"
        assert len(obj.items[0].achievements) == 2

    def test_company_required(self):
        """缺少 company 报错。"""
        with pytest.raises(ValidationError):
            WorkExperienceEntry(position="开发")

    def test_position_required(self):
        """缺少 position 报错。"""
        with pytest.raises(ValidationError):
            WorkExperienceEntry(company="公司")

    def test_empty_entries_default(self):
        """默认空列表。"""
        obj = WorkExperienceContent()
        assert obj.items == []


class TestSkillsContent:
    """专业技能模块 — items 列表（v2 统一结构）。"""

    def test_empty_items_default(self):
        """默认空列表。"""
        obj = SkillsContent()
        assert obj.items == []

    def test_valid_categorized(self):
        """分类技能（使用旧 categories 格式自动迁移）。"""
        obj = SkillsContent(categories=[
            SkillCategory(name="编程语言", items=["Python", "Java", "Go"]),
            SkillCategory(name="框架", items=["FastAPI", "Spring"]),
        ])
        assert len(obj.items) == 5
        assert obj.items[0].name == "Python"
        assert obj.items[0].category == "编程语言"

    def test_valid_flat(self):
        """扁平模式（使用新 items 格式）。"""
        obj = SkillsContent(items=[
            {"name": "Python", "category": "其他"},
            {"name": "FastAPI", "category": "其他"},
        ])
        assert len(obj.items) == 2

    def test_category_name_required(self):
        """SkillItem 缺少 name 报错。"""
        with pytest.raises(ValidationError):
            SkillItem(category="编程语言")


# ═══════════════════════════════════════════════════════════════
# 4. 11 非核心模块 content schema 基本校验
# ═══════════════════════════════════════════════════════════════


class TestNonCoreModules:
    """11 个非核心模块的基本校验。"""

    def test_project_experience(self):
        obj = ProjectExperienceContent(entries=[])
        assert obj.items == []

    def test_language(self):
        from schemas.resume_module import LanguageEntry
        obj = LanguageContent(entries=[LanguageEntry(name="英语", proficiency="CET-6", score="496")])
        assert obj.items[0].name == "英语"

    def test_honors(self):
        from schemas.resume_module import HonorEntry
        obj = HonorsContent(entries=[HonorEntry(title="国家奖学金", date="2024-12")])
        assert obj.items[0].title == "国家奖学金"

    def test_certificates(self):
        from schemas.resume_module import CertificateEntry
        obj = CertificatesContent(entries=[CertificateEntry(name="软考高级", issuer="工信部")])
        assert obj.items[0].name == "软考高级"

    def test_interests(self):
        obj = InterestsContent(items=["阅读", "编程", "羽毛球"])
        assert len(obj.items) == 3

    def test_club_activities(self):
        from schemas.resume_module import ClubActivityEntry
        obj = ClubActivitiesContent(entries=[
            ClubActivityEntry(name="计算机协会", role="会长"),
        ])
        assert obj.items[0].name == "计算机协会"

    def test_publications(self):
        from schemas.resume_module import PublicationEntry
        obj = PublicationsContent(entries=[
            PublicationEntry(title="Deep RAG Survey", authors=["张三"], venue="ICML"),
        ])
        assert obj.items[0].title == "Deep RAG Survey"

    def test_recommendation(self):
        from schemas.resume_module import RecommendationEntry
        obj = RecommendationContent(entries=[
            RecommendationEntry(name="李教授", title="教授", organization="广东海洋大学"),
        ])
        assert obj.items[0].name == "李教授"

    def test_social_links(self):
        obj = SocialLinksContent(items=[{"platform": "GitHub", "url": "https://github.com/test"}])
        assert len(obj.items) == 1
        assert obj.items[0].platform == "GitHub"

    def test_social_links_legacy(self):
        """旧格式社交链接自动迁移。"""
        obj = SocialLinksContent(github="https://github.com/test", linkedin=None)
        assert len(obj.items) == 1
        assert obj.items[0].platform == "GitHub"
        assert obj.items[0].url == "https://github.com/test"

    def test_other_content_required(self):
        """other 模块 content 可为空字符串（v2 改为非必填）。"""
        obj = OtherContent()
        assert obj.content == ""
        obj2 = OtherContent(content="补充信息")
        assert obj2.content == "补充信息"
        assert obj2.title is None

    def test_custom_content_both_required(self):
        """custom 模块 title + content 都必填（无 items 时）。"""
        with pytest.raises(ValidationError):
            CustomContent(title="自定义")
        with pytest.raises(ValidationError):
            CustomContent(content="内容")
        obj = CustomContent(title="自定义", content="内容")
        assert obj.title == "自定义"

    def test_custom_content_entries_mode(self):
        """custom 模块多板块（entries → items 自动迁移）模式。"""
        obj = CustomContent(
            entries=[
                {"title": "项目亮点", "content": "独立开发 3 个 Web 应用"},
                {"title": "开源贡献", "content": "维护 2 个开源项目"},
            ]
        )
        assert len(obj.items) == 2
        assert obj.items[0].title == "项目亮点"
        assert obj.items[1].content == "维护 2 个开源项目"

    def test_custom_content_entries_require_title_and_content(self):
        """entries 每条 title + content 都必填。"""
        with pytest.raises(ValidationError):
            CustomContent(entries=[{"title": "只有标题"}])
        with pytest.raises(ValidationError):
            CustomContent(entries=[{"content": "只有内容"}])

    def test_custom_content_empty_both_rejected(self):
        """无 items 且无 title+content 时校验失败。"""
        with pytest.raises(ValidationError):
            CustomContent()


# ═══════════════════════════════════════════════════════════════
# 5. validate_module_content 函数
# ═══════════════════════════════════════════════════════════════


class TestValidateModuleContent:
    """validate_module_content 四方契约入口。"""

    def test_valid_with_enum(self):
        """枚举入参校验通过。"""
        result = validate_module_content(
            ModuleType.BASIC_INFO, {"name": "张三"}
        )
        assert isinstance(result, BasicInfoContent)
        assert result.name == "张三"

    def test_valid_with_string(self):
        """字符串入参校验通过。"""
        result = validate_module_content("education", {"entries": []})
        assert isinstance(result, EducationContent)

    def test_unknown_module_type_raises(self):
        """未知 module_type 报 ValueError。"""
        with pytest.raises(ValueError, match="未知 module_type"):
            validate_module_content("unknown", {})

    def test_invalid_content_raises_validation_error(self):
        """content 不符合 schema 报 ValidationError。"""
        with pytest.raises(ValidationError):
            validate_module_content(ModuleType.BASIC_INFO, {})  # 缺 name

    def test_all_fifteen_types_validatable(self):
        """全部 15 类型都能通过 validate_module_content 校验。"""
        valid_contents = {
            ModuleType.BASIC_INFO: {"name": "test"},
            ModuleType.EDUCATION: {"entries": []},
            ModuleType.WORK_EXPERIENCE: {"entries": []},
            ModuleType.PROJECT_EXPERIENCE: {"entries": []},
            ModuleType.SKILLS: {"categories": []},
            ModuleType.LANGUAGE: {"entries": []},
            ModuleType.HONORS: {"entries": []},
            ModuleType.CERTIFICATES: {"entries": []},
            ModuleType.INTERESTS: {"items": []},
            ModuleType.CLUB_ACTIVITIES: {"entries": []},
            ModuleType.PUBLICATIONS: {"entries": []},
            ModuleType.RECOMMENDATION: {"entries": []},
            ModuleType.SOCIAL_LINKS: {},
            ModuleType.OTHER: {"content": "text"},
            ModuleType.CUSTOM: {"title": "t", "content": "c"},
        }
        for mt, content in valid_contents.items():
            result = validate_module_content(mt, content)
            assert hasattr(result, "model_dump")

    def test_returns_correct_type_for_each_module(self):
        """每种类型返回正确的 schema 实例。"""
        result = validate_module_content("skills", {"categories": []})
        assert isinstance(result, SkillsContent)

        result = validate_module_content("interests", {"items": ["a"]})
        assert isinstance(result, InterestsContent)


# ═══════════════════════════════════════════════════════════════
# 6. ResumeStyle
# ═══════════════════════════════════════════════════════════════


class TestResumeStyle:
    """简历样式配置。"""

    def test_default_values(self):
        """默认值正确。"""
        style = ResumeStyle()
        assert style.template_id == "default"
        assert style.font_family == "Noto Sans CJK SC"
        assert style.font_size == "14px"
        assert style.line_height == 1.6
        assert style.spacing == "8px"
        assert style.accent_color == "#2563eb"

    def test_custom_values(self):
        """自定义值。"""
        style = ResumeStyle(
            template_id="minimal",
            font_family="Arial",
            font_size="12px",
            line_height=1.8,
            spacing="12px",
            accent_color="#ff0000",
        )
        assert style.template_id == "minimal"
        assert style.accent_color == "#ff0000"

    def test_line_height_range(self):
        """行高范围限制。"""
        with pytest.raises(ValidationError):
            ResumeStyle(line_height=0.5)
        with pytest.raises(ValidationError):
            ResumeStyle(line_height=4.0)

    def test_serialization_roundtrip(self):
        """序列化/反序列化往返。"""
        style = ResumeStyle(template_id="business")
        dumped = style.model_dump()
        restored = ResumeStyle(**dumped)
        assert restored.template_id == "business"

    def test_hidden_modules_default_empty(self):
        """hidden_modules 默认空列表。"""
        assert ResumeStyle().hidden_modules == []

    def test_hidden_modules_custom(self):
        """hidden_modules 自定义值 + 序列化往返。"""
        style = ResumeStyle(hidden_modules=["interests", "social_links"])
        assert style.hidden_modules == ["interests", "social_links"]
        restored = ResumeStyle(**style.model_dump())
        assert restored.hidden_modules == ["interests", "social_links"]

    def test_from_db_dict(self):
        """dict 正常解析。"""
        style = ResumeStyle.from_db({"template_id": "minimal", "accent_color": "#ff0000"})
        assert style.template_id == "minimal"
        assert style.accent_color == "#ff0000"

    def test_from_db_none(self):
        """None → 默认样式。"""
        style = ResumeStyle.from_db(None)
        assert style.template_id == "default"

    def test_from_db_double_serialized_str(self):
        """双重序列化字符串（历史脏数据）→ 正确解析。"""
        import json

        raw = json.dumps({"template_id": "business", "font_size": "12px"})
        style = ResumeStyle.from_db(raw)
        assert style.template_id == "business"
        assert style.font_size == "12px"

    def test_from_db_invalid_str(self):
        """非法字符串 → 回退默认样式。"""
        style = ResumeStyle.from_db("{not-valid-json}")
        assert style.template_id == "default"

    def test_from_db_invalid_field_value(self):
        """字段值非法（如 line_height 超界）→ 回退默认，不抛 500。"""
        style = ResumeStyle.from_db({"line_height": 99.0})
        assert style.template_id == "default"


# ═══════════════════════════════════════════════════════════════
# 7. CRUD schema
# ═══════════════════════════════════════════════════════════════


class TestCRUDSchemas:
    """CRUD schema 序列化/反序列化。"""

    def test_create_with_enum(self):
        """ResumeModuleCreate 接受枚举。"""
        req = ResumeModuleCreate(
            module_type=ModuleType.EDUCATION,
            content={"entries": []},
        )
        assert req.module_type == ModuleType.EDUCATION
        assert req.sort_order == 0

    def test_create_with_string(self):
        """ResumeModuleCreate 接受字符串。"""
        req = ResumeModuleCreate(
            module_type="skills",
            content={"categories": []},
        )
        assert req.module_type == ModuleType.SKILLS

    def test_create_invalid_module_type(self):
        """非法 module_type 报错。"""
        with pytest.raises(ValidationError):
            ResumeModuleCreate(module_type="unknown", content={})

    def test_create_default_sort_order(self):
        """sort_order 默认 0。"""
        req = ResumeModuleCreate(module_type="basic_info", content={"name": "test"})
        assert req.sort_order == 0

    def test_update_partial(self):
        """ResumeModuleUpdate 部分更新。"""
        update = ResumeModuleUpdate(content={"name": "新名字"})
        assert update.content is not None
        assert update.sort_order is None

    def test_update_sort_order_only(self):
        """仅更新 sort_order。"""
        update = ResumeModuleUpdate(sort_order=5)
        assert update.sort_order == 5
        assert update.content is None

    def test_response_from_attributes(self):
        """ResumeModuleResponse 支持 from_attributes。"""
        from datetime import datetime
        # 模拟 ORM 对象
        class FakeORM:
            id = 1
            resume_id = 10
            module_type = ModuleType.BASIC_INFO
            content = {"name": "张三"}
            sort_order = 0
            created_at = datetime(2026, 7, 31)

        response = ResumeModuleResponse.model_validate(FakeORM())
        assert response.id == 1
        assert response.module_type == ModuleType.BASIC_INFO
        assert response.content["name"] == "张三"

    def test_list_response(self):
        """ResumeModuleListResponse。"""
        from datetime import datetime
        items = [
            ResumeModuleResponse(
                id=1, resume_id=1, module_type=ModuleType.BASIC_INFO,
                content={"name": "test"}, sort_order=0,
                created_at=datetime(2026, 7, 31),
            ),
        ]
        lst = ResumeModuleListResponse(items=items, total=1)
        assert lst.total == 1
        assert len(lst.items) == 1


# ═══════════════════════════════════════════════════════════════
# 8. 序列化往返（四方契约一致性）
# ═══════════════════════════════════════════════════════════════


class TestSerializationRoundtrip:
    """schema → dict → schema 往返一致性。"""

    def test_basic_info_roundtrip(self):
        """BasicInfoContent 往返。"""
        original = BasicInfoContent(name="张三", phone="138", email="t@t.com")
        dumped = original.model_dump()
        restored = BasicInfoContent(**dumped)
        assert restored == original

    def test_education_roundtrip(self):
        """EducationContent 往返。"""
        original = EducationContent(entries=[
            EducationEntry(school="A", degree="本科"),
        ])
        dumped = original.model_dump()
        restored = EducationContent(**dumped)
        assert restored.items[0].school == "A"

    def test_work_experience_roundtrip(self):
        """WorkExperienceContent 往返。"""
        original = WorkExperienceContent(entries=[
            WorkExperienceEntry(company="B", position="C", achievements=["a", "b"]),
        ])
        dumped = original.model_dump()
        restored = WorkExperienceContent(**dumped)
        assert restored.items[0].achievements == ["a", "b"]

    def test_skills_roundtrip(self):
        """SkillsContent 往返（旧 categories 格式迁移后）。"""
        original = SkillsContent(categories=[
            SkillCategory(name="lang", items=["Python"]),
        ])
        dumped = original.model_dump()
        restored = SkillsContent(**dumped)
        assert restored.items[0].name == "Python"
        assert restored.items[0].category == "lang"

    def test_json_serialization(self):
        """model_validate_json 正确解析 JSON 字符串。"""
        import json
        data = {"name": "张三", "phone": "138"}
        json_str = json.dumps(data)
        obj = BasicInfoContent.model_validate_json(json_str)
        assert obj.name == "张三"


# ═══════════════════════════════════════════════════════════════
# 9. 边界用例
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """边界用例。"""

    def test_basic_info_extra_fields_ignored(self):
        """额外字段被忽略（Pydantic v2 默认行为）。"""
        obj = BasicInfoContent(name="张三", unexpected_field="value")
        assert obj.name == "张三"
        assert not hasattr(obj, "unexpected_field")

    def test_skills_empty_categories(self):
        """空 categories 列表迁移为空 items。"""
        obj = SkillsContent(categories=[])
        assert obj.items == []

    def test_interests_empty_items(self):
        """空 items 列表合法。"""
        obj = InterestsContent(items=[])
        assert obj.items == []

    def test_other_content_max_length(self):
        """content 达到最大长度。"""
        obj = OtherContent(content="a" * 5000)
        assert len(obj.content) == 5000

    def test_other_content_exceeds_max_length(self):
        """content 超过最大长度报错。"""
        with pytest.raises(ValidationError):
            OtherContent(content="a" * 5001)
