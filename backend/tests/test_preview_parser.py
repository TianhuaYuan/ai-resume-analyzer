"""测试：preview（content hash 缓存 + 守卫）+ parse-to-modules 反解析（校验+重试）。

测试覆盖：
- resume_preview: content hash 计算、缓存命中/未命中、TTL 过期、LRU 淘汰、零模块守卫
- resume_parser: JSON 提取、模块校验、重试逻辑、空文本拒绝、部分成功
- API: GET /preview、POST /parse-to-modules 端点集成
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.resume_preview import (
    _compute_content_hash,
    _get_cached,
    _set_cached,
    clear_preview_cache,
    get_cache_stats,
    get_resume_preview,
)
from services.resume_parser import (
    _build_error_feedback,
    _build_user_prompt,
    _extract_json_from_response,
    _validate_parsed_modules,
    parse_text_to_modules,
)


# ═══════════════════════════════════════════════════════════
# 测试辅助
# ═══════════════════════════════════════════════════════════


def _make_module(module_type="basic_info", content=None, sort_order=0, mod_id=1):
    """构造一个模拟的 ResumeModule 对象。"""
    if content is None:
        content = {"name": "张三", "phone": "13800138000"}
    mod = MagicMock()
    mod.module_type = module_type
    mod.content = content
    mod.sort_order = sort_order
    mod.id = mod_id
    return mod


def _make_resume(modules=None, style=None, filename="测试简历"):
    """构造一个模拟的 Resume 对象。"""
    resume = MagicMock()
    resume.id = 1
    resume.filename = filename
    resume.style = style
    resume.modules = modules or []
    return resume


_VALID_BASIC_INFO = {"name": "张三", "phone": "13800138000", "email": "zhangsan@example.com"}
_VALID_EDUCATION = {"entries": [{"school": "广东海洋大学", "degree": "本科", "major": "软件工程"}]}
_VALID_SKILLS = {"categories": [{"name": "编程语言", "items": ["Python", "Java"]}]}
_VALID_WORK = {"entries": [{"company": "字节跳动", "position": "后端开发", "description": "负责 API 开发"}]}

# 解析反解析测试的源文本：必须包含上方所有 _VALID_* 字段值，
# 否则 A2 字段级溯源校验（verify_fields_in_original_text）会因字段无法在原文定位而失败。
_FULL_PARSE_TEXT = (
    "张三\n13800138000\nzhangsan@example.com\n"
    "广东海洋大学\n本科\n软件工程\n"
    "字节跳动\n后端开发\n负责 API 开发"
)


# ═══════════════════════════════════════════════════════════
# 1. Content Hash 计算测试
# ═══════════════════════════════════════════════════════════


class TestComputeContentHash:
    """Content hash 计算测试。"""

    def test_same_content_same_hash(self):
        """相同内容 → 相同 hash。"""
        from schemas.resume_module import ResumeStyle

        modules = [_make_module(mod_id=1)]
        style = ResumeStyle()
        hash1 = _compute_content_hash(modules, style, "简历.pdf")
        hash2 = _compute_content_hash(modules, style, "简历.pdf")
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """不同内容 → 不同 hash。"""
        from schemas.resume_module import ResumeStyle

        modules1 = [_make_module(content={"name": "张三"}, mod_id=1)]
        modules2 = [_make_module(content={"name": "李四"}, mod_id=1)]
        style = ResumeStyle()
        hash1 = _compute_content_hash(modules1, style, "简历.pdf")
        hash2 = _compute_content_hash(modules2, style, "简历.pdf")
        assert hash1 != hash2

    def test_different_style_different_hash(self):
        """不同样式 → 不同 hash。"""
        from schemas.resume_module import ResumeStyle

        modules = [_make_module(mod_id=1)]
        style1 = ResumeStyle(template_id="default")
        style2 = ResumeStyle(template_id="minimal")
        hash1 = _compute_content_hash(modules, style1, "简历.pdf")
        hash2 = _compute_content_hash(modules, style2, "简历.pdf")
        assert hash1 != hash2

    def test_different_filename_different_hash(self):
        """不同文件名 → 不同 hash。"""
        from schemas.resume_module import ResumeStyle

        modules = [_make_module(mod_id=1)]
        style = ResumeStyle()
        hash1 = _compute_content_hash(modules, style, "简历1.pdf")
        hash2 = _compute_content_hash(modules, style, "简历2.pdf")
        assert hash1 != hash2

    def test_different_sort_order_different_hash(self):
        """不同排序 → 不同 hash。"""
        from schemas.resume_module import ResumeStyle

        modules1 = [
            _make_module(module_type="basic_info", sort_order=0, mod_id=1),
            _make_module(module_type="education", sort_order=1, mod_id=2),
        ]
        modules2 = [
            _make_module(module_type="education", sort_order=0, mod_id=2),
            _make_module(module_type="basic_info", sort_order=1, mod_id=1),
        ]
        style = ResumeStyle()
        hash1 = _compute_content_hash(modules1, style, "简历.pdf")
        hash2 = _compute_content_hash(modules2, style, "简历.pdf")
        assert hash1 != hash2

    def test_hash_is_hex_string(self):
        """hash 是 64 字符的 hex 字符串（SHA256）。"""
        from schemas.resume_module import ResumeStyle

        modules = [_make_module()]
        style = ResumeStyle()
        h = _compute_content_hash(modules, style, "test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ═══════════════════════════════════════════════════════════
# 2. 缓存测试
# ═══════════════════════════════════════════════════════════


class TestPreviewCache:
    """预览缓存测试。"""

    def setup_method(self):
        clear_preview_cache()

    def teardown_method(self):
        clear_preview_cache()

    def test_cache_set_and_get(self):
        """写入缓存后可以读取。"""
        _set_cached("hash123", "<html>test</html>")
        result = _get_cached("hash123")
        assert result == "<html>test</html>"

    def test_cache_miss_for_unknown_key(self):
        """未知 key → None。"""
        result = _get_cached("nonexistent")
        assert result is None

    def test_cache_lru_eviction(self):
        """超过上限时 LRU 淘汰。"""
        from services.resume_preview import _MAX_CACHE_ENTRIES, _preview_cache

        # 填满缓存
        for i in range(_MAX_CACHE_ENTRIES):
            _set_cached(f"hash_{i}", f"<html>{i}</html>")

        assert len(_preview_cache) == _MAX_CACHE_ENTRIES

        # 再加一个，最老的应该被淘汰
        _set_cached("hash_new", "<html>new</html>")
        assert len(_preview_cache) == _MAX_CACHE_ENTRIES
        assert _get_cached("hash_0") is None  # 最老的被淘汰
        assert _get_cached("hash_new") == "<html>new</html>"

    def test_cache_lru_update_on_get(self):
        """get 操作更新 LRU 顺序。"""
        from services.resume_preview import _MAX_CACHE_ENTRIES

        # 填满缓存
        for i in range(_MAX_CACHE_ENTRIES):
            _set_cached(f"hash_{i}", f"<html>{i}</html>")

        # 访问第一个，使其变为最近使用
        _get_cached("hash_0")

        # 再加一个，hash_1 应该被淘汰（而不是 hash_0）
        _set_cached("hash_new", "<html>new</html>")
        assert _get_cached("hash_0") == "<html>0</html>"  # 仍然存在
        assert _get_cached("hash_1") is None  # 被淘汰

    def test_cache_stats(self):
        """缓存统计信息正确。"""
        _set_cached("hash1", "<html>1</html>")
        _set_cached("hash2", "<html>2</html>")
        stats = get_cache_stats()
        assert stats["total_entries"] == 2
        assert stats["active_entries"] == 2
        assert stats["expired_entries"] == 0

    def test_clear_cache(self):
        """清空缓存。"""
        _set_cached("hash1", "<html>1</html>")
        count = clear_preview_cache()
        assert count == 1
        assert _get_cached("hash1") is None


class TestPreviewCacheTTL:
    """缓存 TTL 过期测试。"""

    def setup_method(self):
        clear_preview_cache()

    def teardown_method(self):
        clear_preview_cache()

    def test_cache_ttl_expiration(self):
        """过期后缓存失效。"""
        from services.resume_preview import _CACHE_TTL_SECONDS

        # 写入缓存
        _set_cached("hash_ttl", "<html>test</html>")

        # 手动修改 timestamp 为过期时间
        from services.resume_preview import _preview_cache
        html, _ = _preview_cache["hash_ttl"]
        _preview_cache["hash_ttl"] = (html, time.time() - _CACHE_TTL_SECONDS - 1)

        # 应该返回 None（已过期）
        result = _get_cached("hash_ttl")
        assert result is None

    def test_cache_not_expired_within_ttl(self):
        """TTL 内缓存有效。"""
        _set_cached("hash_fresh", "<html>fresh</html>")
        result = _get_cached("hash_fresh")
        assert result == "<html>fresh</html>"


# ═══════════════════════════════════════════════════════════
# 3. get_resume_preview 集成测试
# ═══════════════════════════════════════════════════════════


class TestGetResumePreview:
    """get_resume_preview 集成测试。"""

    def setup_method(self):
        clear_preview_cache()

    def teardown_method(self):
        clear_preview_cache()

    async def test_preview_cache_miss_then_hit(self, db_session, registered_user):
        """第一次 miss → 渲染并缓存 → 第二次 hit。"""
        from services.resume_builder import create_builder_resume
        from schemas.resume_module import (
            BuilderCreateRequest,
            ResumeModuleCreate,
            ModuleType,
        )

        user_id = registered_user["id"]

        # 创建带模块的简历
        body = BuilderCreateRequest(
            filename="测试简历",
            modules=[
                ResumeModuleCreate(
                    module_type=ModuleType.BASIC_INFO,
                    content=_VALID_BASIC_INFO,
                    sort_order=0,
                ),
            ],
        )
        resume, modules = await create_builder_resume(db_session, user_id, body)

        # 第一次调用 → cache miss
        html1, hit1 = await get_resume_preview(db_session, user_id, resume.id)
        assert hit1 is False
        assert "<html" in html1.lower() or "<section" in html1.lower()

        # 第二次调用 → cache hit
        html2, hit2 = await get_resume_preview(db_session, user_id, resume.id)
        assert hit2 is True
        assert html2 == html1

    async def test_preview_404_nonexistent_resume(self, db_session, registered_user):
        """不存在的简历 → 404。"""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await get_resume_preview(db_session, registered_user["id"], 99999)
        assert exc.value.status_code == 404

    async def test_preview_zero_modules_guard(self, db_session, registered_user):
        """builder 源空简历 → 允许预览（渲染空模板）。

        spec 边界 13: 零模块守卫仅拦截 source=upload 的简历；builder 简历
        即使空模块也允许预览（#7 修复：新建 builder 简历实时预览）。
        """
        from services.resume_builder import create_builder_resume
        from schemas.resume_module import BuilderCreateRequest

        body = BuilderCreateRequest(filename="空简历", modules=[])
        resume, _ = await create_builder_resume(db_session, registered_user["id"], body)

        # builder 源空简历不拦截，渲染出空模板 HTML
        html, _ = await get_resume_preview(db_session, registered_user["id"], resume.id)
        assert isinstance(html, str) and len(html) > 0

    async def test_preview_cache_invalidates_on_content_change(self, db_session, registered_user):
        """内容变更后缓存失效（hash 不同 → miss）。"""
        from services.resume_builder import (
            create_builder_resume,
            update_resume_draft,
        )
        from schemas.resume_module import (
            BuilderCreateRequest,
            BuilderDraftUpdateRequest,
            ResumeModuleCreate,
            ModuleType,
        )

        user_id = registered_user["id"]

        # 创建简历
        body = BuilderCreateRequest(
            filename="测试简历",
            modules=[
                ResumeModuleCreate(
                    module_type=ModuleType.BASIC_INFO,
                    content=_VALID_BASIC_INFO,
                    sort_order=0,
                ),
            ],
        )
        resume, _ = await create_builder_resume(db_session, user_id, body)

        # 第一次预览 → miss
        html1, hit1 = await get_resume_preview(db_session, user_id, resume.id)
        assert hit1 is False

        # 更新模块内容
        draft_body = BuilderDraftUpdateRequest(
            modules=[
                ResumeModuleCreate(
                    module_type=ModuleType.BASIC_INFO,
                    content={"name": "李四", "phone": "13900139000"},
                    sort_order=0,
                ),
            ],
        )
        await update_resume_draft(db_session, user_id, resume.id, draft_body)

        # 第二次预览 → 应该 miss（内容变了，hash 不同）
        html2, hit2 = await get_resume_preview(db_session, user_id, resume.id)
        assert hit2 is False
        assert html2 != html1  # HTML 内容不同


# ═══════════════════════════════════════════════════════════
# 4. JSON 提取测试
# ═══════════════════════════════════════════════════════════


class TestExtractJson:
    """_extract_json_from_response 测试。"""

    def test_plain_json_array(self):
        """纯 JSON 数组。"""
        response = '[{"module_type": "basic_info", "content": {"name": "张三"}, "sort_order": 0}]'
        result = _extract_json_from_response(response)
        assert len(result) == 1
        assert result[0]["module_type"] == "basic_info"

    def test_json_in_code_block(self):
        """```json 代码块包裹。"""
        response = '```json\n[{"module_type": "basic_info", "content": {"name": "张三"}, "sort_order": 0}]\n```'
        result = _extract_json_from_response(response)
        assert len(result) == 1
        assert result[0]["module_type"] == "basic_info"

    def test_json_with_surrounding_text(self):
        """带前后解释文字。"""
        response = '''以下是解析结果：
[{"module_type": "basic_info", "content": {"name": "张三"}, "sort_order": 0}]
希望对您有帮助！'''
        result = _extract_json_from_response(response)
        assert len(result) == 1
        assert result[0]["module_type"] == "basic_info"

    def test_json_multiple_modules(self):
        """多个模块。"""
        response = '''[
            {"module_type": "basic_info", "content": {"name": "张三"}, "sort_order": 0},
            {"module_type": "education", "content": {"entries": [{"school": "海大"}]}, "sort_order": 1}
        ]'''
        result = _extract_json_from_response(response)
        assert len(result) == 2

    def test_no_json_array_raises(self):
        """无 JSON 数组 → ValueError。"""
        with pytest.raises(ValueError, match="未找到 JSON 数组"):
            _extract_json_from_response("这不是 JSON")

    def test_invalid_json_raises(self):
        """无效 JSON → JSONDecodeError。"""
        with pytest.raises(json.JSONDecodeError):
            _extract_json_from_response("[invalid json content]")

    def test_json_object_not_array_raises(self):
        """JSON 对象（非数组，无方括号）→ ValueError。"""
        with pytest.raises(ValueError, match="未找到 JSON 数组"):
            _extract_json_from_response('{"key": "value"}')

    def test_empty_array(self):
        """空数组。"""
        result = _extract_json_from_response("[]")
        assert result == []


# ═══════════════════════════════════════════════════════════
# 5. 模块校验测试
# ═══════════════════════════════════════════════════════════


class TestValidateParsedModules:
    """_validate_parsed_modules 测试。"""

    def test_all_valid_modules(self):
        """全部合法模块 → 全部通过。"""
        raw = [
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "education", "content": _VALID_EDUCATION, "sort_order": 1},
            {"module_type": "skills", "content": _VALID_SKILLS, "sort_order": 2},
        ]
        validated, errors = _validate_parsed_modules(raw)
        assert len(validated) == 3
        assert len(errors) == 0

    def test_missing_module_type(self):
        """缺少 module_type → 错误。"""
        raw = [{"content": {"name": "张三"}, "sort_order": 0}]
        validated, errors = _validate_parsed_modules(raw)
        assert len(validated) == 0
        assert len(errors) == 1
        assert "module_type" in errors[0]

    def test_unknown_module_type(self):
        """未知 module_type → 错误。"""
        raw = [{"module_type": "unknown_type", "content": {}, "sort_order": 0}]
        validated, errors = _validate_parsed_modules(raw)
        assert len(validated) == 0
        assert len(errors) == 1
        assert "unknown_type" in errors[0]

    def test_invalid_content_missing_required_field(self):
        """content 缺少必填字段 → 错误。"""
        raw = [
            {"module_type": "basic_info", "content": {}, "sort_order": 0},  # 缺 name
        ]
        validated, errors = _validate_parsed_modules(raw)
        assert len(validated) == 0
        assert len(errors) == 1
        assert "basic_info" in errors[0]

    def test_content_not_dict(self):
        """content 不是 dict → 错误。"""
        raw = [{"module_type": "basic_info", "content": "not a dict", "sort_order": 0}]
        validated, errors = _validate_parsed_modules(raw)
        assert len(validated) == 0
        assert len(errors) == 1

    def test_raw_not_dict(self):
        """元素不是 dict → 错误。"""
        raw = ["not a dict", 42]
        validated, errors = _validate_parsed_modules(raw)
        assert len(validated) == 0
        assert len(errors) == 2

    def test_partial_valid(self):
        """部分合法部分非法 → 合法的通过，非法的报错。"""
        raw = [
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "basic_info", "content": {}, "sort_order": 1},  # 缺 name
            {"module_type": "education", "content": _VALID_EDUCATION, "sort_order": 2},
        ]
        validated, errors = _validate_parsed_modules(raw)
        assert len(validated) == 2
        assert len(errors) == 1

    def test_sort_order_defaults_to_index(self):
        """sort_order 缺失时默认为索引。"""
        raw = [{"module_type": "basic_info", "content": _VALID_BASIC_INFO}]
        validated, _ = _validate_parsed_modules(raw)
        assert validated[0].sort_order == 0

    def test_sort_order_negative_clamped_to_index(self):
        """sort_order 为负数时用索引替代。"""
        raw = [{"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": -5}]
        validated, _ = _validate_parsed_modules(raw)
        assert validated[0].sort_order == 0


# ═══════════════════════════════════════════════════════════
# 6. Prompt 构建测试
# ═══════════════════════════════════════════════════════════


class TestPromptBuilder:
    """Prompt 构建测试。"""

    def test_user_prompt_contains_text(self):
        """prompt 包含简历文本。"""
        text = "张三，男，24岁，手机：13800138000"
        prompt = _build_user_prompt(text)
        assert text in prompt

    def test_user_prompt_without_feedback(self):
        """无错误反馈时 prompt 不包含反馈部分。"""
        prompt = _build_user_prompt("简历文本")
        assert "上次解析包含无原文证据" not in prompt

    def test_user_prompt_with_feedback(self):
        """有错误反馈时 prompt 包含反馈。"""
        feedback = "模块 0: 缺少 name 字段"
        prompt = _build_user_prompt("简历文本", feedback)
        assert "上次解析包含无原文证据" in prompt
        assert feedback in prompt

    def test_error_feedback_format(self):
        """错误反馈格式正确。"""
        errors = ["错误1", "错误2"]
        feedback = _build_error_feedback(errors)
        assert "- 错误1" in feedback
        assert "- 错误2" in feedback


# ═══════════════════════════════════════════════════════════
# 7. parse_text_to_modules 测试（mock LLM）
# ═══════════════════════════════════════════════════════════


class TestParseTextToModules:
    """parse_text_to_modules 测试（mock LLM）。"""

    async def test_empty_text_raises(self):
        """空文本 → ValueError。"""
        with pytest.raises(ValueError, match="不能为空"):
            await parse_text_to_modules("")
        with pytest.raises(ValueError, match="不能为空"):
            await parse_text_to_modules("   ")

    async def test_successful_parse_first_try(self):
        """第一次成功解析（无重试）。"""
        llm_response = json.dumps([
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "education", "content": _VALID_EDUCATION, "sort_order": 1},
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=llm_response):
            modules = await parse_text_to_modules(_FULL_PARSE_TEXT)

        assert len(modules) == 2
        assert modules[0].module_type.value == "basic_info"
        assert modules[1].module_type.value == "education"

    async def test_retry_on_validation_error(self):
        """校验失败 → 回灌重试 → 第二次成功。"""
        bad_response = json.dumps([
            {"module_type": "basic_info", "content": {}, "sort_order": 0},  # 缺 name
        ])
        good_response = json.dumps([
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, side_effect=[bad_response, good_response]):
            modules = await parse_text_to_modules(_FULL_PARSE_TEXT)

        assert len(modules) == 1
        assert modules[0].module_type.value == "basic_info"
        assert modules[0].content["name"] == "张三"

    async def test_retry_on_json_parse_error(self):
        """JSON 解析失败 → 重试 → 成功。"""
        bad_response = "这不是有效的 JSON 格式"
        good_response = json.dumps([
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, side_effect=[bad_response, good_response]):
            modules = await parse_text_to_modules(_FULL_PARSE_TEXT)

        assert len(modules) == 1

    async def test_all_fail_after_retry(self):
        """重试后仍失败 → ValueError。"""
        bad_response = json.dumps([
            {"module_type": "basic_info", "content": {}, "sort_order": 0},  # 缺 name
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=bad_response):
            with pytest.raises(ValueError, match="校验失败"):
                await parse_text_to_modules(_FULL_PARSE_TEXT)

    async def test_empty_llm_response_retry(self):
        """LLM 返回空 → 重试 → 成功。"""
        good_response = json.dumps([
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, side_effect=["", good_response]):
            modules = await parse_text_to_modules(_FULL_PARSE_TEXT)

        assert len(modules) == 1

    async def test_empty_llm_response_all_fail(self):
        """LLM 两次都返回空 → ValueError。"""
        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=""):
            with pytest.raises(ValueError, match="空响应"):
                await parse_text_to_modules(_FULL_PARSE_TEXT)

    async def test_empty_array_raises(self):
        """LLM 返回空数组 [] → 重试 → 仍为空 → ValueError（不静默返回空列表）。"""
        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value="[]"):
            with pytest.raises(ValueError, match="空数组"):
                await parse_text_to_modules(_FULL_PARSE_TEXT)

    async def test_empty_array_retry_success(self):
        """LLM 先返回空数组 [] → 重试成功。"""
        good_response = json.dumps([
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, side_effect=["[]", good_response]):
            modules = await parse_text_to_modules(_FULL_PARSE_TEXT)

        assert len(modules) == 1
        assert modules[0].module_type.value == "basic_info"

    async def test_trailing_bracket_handled(self):
        """输出末尾含无关 ]（rfind 误命中）→ 抗截断提取到正确数组。"""
        # LLM 输出带结尾解释文字且含 ]，旧逻辑 rfind 命中末尾 ] 导致 json.loads 失败；
        # 抗截断逻辑应从后往前找第一个能完整解析的数组。
        response = (
            json.dumps([
                {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            ])
            + " 以上是解析结果]"
        )

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=response):
            modules = await parse_text_to_modules(_FULL_PARSE_TEXT)

        assert len(modules) == 1
        assert modules[0].module_type.value == "basic_info"

    async def test_rejects_partial_success(self):
        """部分非法模块 → 拒绝局部成功（宁可失败，防 LLM 编造污染表单）。"""
        partial_response = json.dumps([
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "basic_info", "content": {}, "sort_order": 1},  # 缺 name
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=partial_response):
            with pytest.raises(ValueError):
                await parse_text_to_modules(_FULL_PARSE_TEXT)

    async def test_llm_call_failure_raises(self):
        """LLM 调用异常 → ValueError。"""
        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, side_effect=RuntimeError("API 挂了")):
            with pytest.raises(ValueError, match="LLM 调用失败"):
                await parse_text_to_modules(_FULL_PARSE_TEXT)

    async def test_json_in_code_block(self):
        """LLM 输出 ```json 代码块 → 正确解析。"""
        llm_response = f"""```json
{json.dumps([
    {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
])}
```"""

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=llm_response):
            modules = await parse_text_to_modules(_FULL_PARSE_TEXT)

        assert len(modules) == 1

    async def test_user_id_passed_to_llm(self):
        """user_id 正确传递给 llm_generate（用于记账）。"""
        llm_response = json.dumps([
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=llm_response) as mock_llm:
            await parse_text_to_modules(_FULL_PARSE_TEXT, user_id=42)
            # 检查 user_id 被传递
            assert mock_llm.call_args.kwargs.get("user_id") == 42


# ═══════════════════════════════════════════════════════════
# 8. API 端点集成测试
# ═══════════════════════════════════════════════════════════


class TestPreviewAPI:
    """GET /resumes/{id}/preview 端点测试。"""

    async def test_preview_success(self, client, auth_headers, db_session, registered_user):
        """成功获取预览 HTML。"""
        from services.resume_builder import create_builder_resume
        from schemas.resume_module import (
            BuilderCreateRequest,
            ResumeModuleCreate,
            ModuleType,
        )

        clear_preview_cache()

        body = BuilderCreateRequest(
            filename="API测试简历",
            modules=[
                ResumeModuleCreate(
                    module_type=ModuleType.BASIC_INFO,
                    content=_VALID_BASIC_INFO,
                    sort_order=0,
                ),
            ],
        )
        resume, _ = await create_builder_resume(db_session, registered_user["id"], body)

        resp = await client.get(
            f"/api/v1/resumes/{resume.id}/preview",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert resp.headers.get("x-cache-hit") == "false"

        # 第二次请求 → cache hit
        resp2 = await client.get(
            f"/api/v1/resumes/{resume.id}/preview",
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        assert resp2.headers.get("x-cache-hit") == "true"

    async def test_preview_404(self, client, auth_headers):
        """不存在的简历 → 404。"""
        resp = await client.get(
            "/api/v1/resumes/99999/preview",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_preview_zero_modules(self, client, auth_headers, db_session, registered_user):
        """builder 源空简历 → 允许预览（200，渲染空模板）。

        spec 边界 13: 零模块守卫仅拦截 upload 源；builder 简历空模块允许预览（#7）。
        """
        from services.resume_builder import create_builder_resume
        from schemas.resume_module import BuilderCreateRequest

        clear_preview_cache()

        body = BuilderCreateRequest(filename="空简历", modules=[])
        resume, _ = await create_builder_resume(db_session, registered_user["id"], body)

        resp = await client.get(
            f"/api/v1/resumes/{resume.id}/preview",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    async def test_preview_unauthorized(self, client):
        """未登录 → 401。"""
        resp = await client.get("/api/v1/resumes/1/preview")
        assert resp.status_code == 401


class TestParseToModulesAPI:
    """POST /resumes/parse-to-modules 端点测试。"""

    async def test_parse_success(self, client, auth_headers):
        """成功反解析。"""
        llm_response = json.dumps([
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "education", "content": _VALID_EDUCATION, "sort_order": 1},
        ])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=llm_response):
            resp = await client.post(
                "/api/v1/resumes/parse-to-modules",
                json={"text": _FULL_PARSE_TEXT},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["modules"][0]["module_type"] == "basic_info"

    async def test_parse_empty_text(self, client, auth_headers):
        """空文本 → 422。"""
        resp = await client.post(
            "/api/v1/resumes/parse-to-modules",
            json={"text": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_parse_short_text(self, client, auth_headers):
        """过短文本 → 422。"""
        resp = await client.post(
            "/api/v1/resumes/parse-to-modules",
            json={"text": "短"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_parse_too_long_text(self, client, auth_headers):
        """过长文本 → 422。"""
        resp = await client.post(
            "/api/v1/resumes/parse-to-modules",
            json={"text": "x" * 50001},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_parse_unauthorized(self, client):
        """未登录 → 401。"""
        resp = await client.post(
            "/api/v1/resumes/parse-to-modules",
            json={"text": "一些简历文本内容"},
        )
        assert resp.status_code == 401

    async def test_parse_retry_on_failure(self, client, auth_headers):
        """校验失败 → 重试 → 成功。"""
        bad = json.dumps([{"module_type": "basic_info", "content": {}, "sort_order": 0}])
        good = json.dumps([{"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0}])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, side_effect=[bad, good]):
            resp = await client.post(
                "/api/v1/resumes/parse-to-modules",
                json={"text": _FULL_PARSE_TEXT},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_parse_all_fail(self, client, auth_headers):
        """全部失败 → 422。"""
        bad = json.dumps([{"module_type": "basic_info", "content": {}, "sort_order": 0}])

        with patch("services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=bad):
            resp = await client.post(
                "/api/v1/resumes/parse-to-modules",
                json={"text": _FULL_PARSE_TEXT},
                headers=auth_headers,
            )

        assert resp.status_code == 422
