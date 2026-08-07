"""T28 测试：builder 工具 + 编辑锁 + 短事务。

测试覆盖：
1. edit_lock: 获取/续期/释放/查询锁状态、互斥、CAS 释放
2. _update_module_short_txn: 短事务写入模块（新建/更新）
3. _replace_all_modules_short_txn: 全量替换模块
4. generate_module: LLM 生成 + 写入
5. check_module: ATS 检查（只读）
6. modify_module: LLM 修改 + 写入
7. rewrite_resume: generate/optimize 双模式
8. ask_info: 追问建议（只读）
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.edit_lock import (
    EDIT_LOCK_TTL,
    acquire_edit_lock,
    get_lock_holder,
    is_edit_locked,
    release_edit_lock,
    renew_edit_lock,
)
from services.rag.pipeline import LLMToolResponse, ToolCall
from services.react_agent.tools.base import ToolRetryError
from tests.conftest import AsyncSessionTest


# ═══════════════════════════════════════════════════════════════
# 测试辅助
# ═══════════════════════════════════════════════════════════════

_VALID_BASIC_INFO = {"name": "张三", "phone": "13800138000", "email": "zhangsan@example.com"}
_VALID_EDUCATION = {"entries": [{"school": "广东海洋大学", "degree": "本科", "major": "软件工程"}]}
_VALID_SKILLS = {"categories": [{"name": "编程语言", "items": ["Python", "Java"]}]}
_VALID_WORK = {
    "entries": [{"company": "字节跳动", "position": "后端开发", "description": "负责 API 开发"}]
}


def _tool_resp(name: str, args: dict) -> LLMToolResponse:
    """构造 llm_generate_with_tools 的 mock 返回（单个工具调用）。"""
    return LLMToolResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_1", name=name, arguments=json.dumps(args, ensure_ascii=False))
        ],
    )


async def _create_test_resume(db_session, user_id, modules=None):
    """创建测试简历 + 模块。"""
    from schemas.resume_module import (
        BuilderCreateRequest,
        ResumeModuleCreate,
        ModuleType,
    )
    from services.resume_builder import create_builder_resume

    if modules is None:
        modules = [
            ResumeModuleCreate(
                module_type=ModuleType.BASIC_INFO,
                content=_VALID_BASIC_INFO,
                sort_order=0,
            ),
        ]

    body = BuilderCreateRequest(filename="测试简历", modules=modules)
    resume, mods = await create_builder_resume(db_session, user_id, body)
    return resume, mods


# ═══════════════════════════════════════════════════════════════
# 1. 编辑锁测试
# ═══════════════════════════════════════════════════════════════


class TestEditLock:
    """编辑锁服务测试。"""

    async def test_acquire_lock_success(self):
        """获取锁成功 → 返回 token。"""
        token = await acquire_edit_lock(resume_id=1, user_id=100)
        assert token is not None
        assert "100:" in token

    async def test_acquire_lock_mutex(self):
        """第二个用户获取同一简历的锁 → 失败。"""
        token1 = await acquire_edit_lock(resume_id=2, user_id=100)
        token2 = await acquire_edit_lock(resume_id=2, user_id=200)
        assert token1 is not None
        assert token2 is None

    async def test_acquire_lock_same_user_reacquire(self):
        """同一用户再次获取锁 → 成功（续期）。"""
        token1 = await acquire_edit_lock(resume_id=3, user_id=100)
        token2 = await acquire_edit_lock(resume_id=3, user_id=100)
        assert token1 is not None
        assert token2 is not None

    async def test_release_lock_success(self):
        """正确 token 释放锁 → 成功。"""
        token = await acquire_edit_lock(resume_id=4, user_id=100)
        result = await release_edit_lock(resume_id=4, user_id=100, lock_token=token)
        assert result is True
        assert await is_edit_locked(4) is False

    async def test_release_lock_wrong_token(self):
        """错误 token 释放锁 → 失败。"""
        await acquire_edit_lock(resume_id=5, user_id=100)
        result = await release_edit_lock(resume_id=5, user_id=100, lock_token="wrong_token")
        assert result is False
        assert await is_edit_locked(5) is True

    async def test_renew_lock_success(self):
        """心跳续期成功。"""
        token = await acquire_edit_lock(resume_id=6, user_id=100)
        result = await renew_edit_lock(resume_id=6, user_id=100, lock_token=token)
        assert result is True

    async def test_renew_lock_wrong_token(self):
        """错误 token 续期 → 失败。"""
        await acquire_edit_lock(resume_id=7, user_id=100)
        result = await renew_edit_lock(resume_id=7, user_id=100, lock_token="wrong")
        assert result is False

    async def test_is_edit_locked(self):
        """查询锁状态。"""
        assert await is_edit_locked(8) is False
        await acquire_edit_lock(resume_id=8, user_id=100)
        assert await is_edit_locked(8) is True

    async def test_get_lock_holder(self):
        """获取锁持有者 user_id。"""
        assert await get_lock_holder(9) is None
        await acquire_edit_lock(resume_id=9, user_id=100)
        holder = await get_lock_holder(9)
        assert holder == 100

    async def test_get_lock_holder_no_lock(self):
        """无锁时返回 None。"""
        result = await get_lock_holder(99999)
        assert result is None

    async def test_edit_lock_ttl_default(self):
        """默认 TTL = 120s。"""
        assert EDIT_LOCK_TTL == 120

    async def test_inmemory_redis_renew_keeps_lock(self):
        """回归测试：InMemoryRedis.eval 续期不能删除锁（修复 409 根因）。

        原实现把所有 eval 脚本当 DEL 执行，renew_edit_lock 走 eval 后锁被删，
        导致后续心跳全部 409。修复后 RENEW 脚本应保持锁存在且刷新 TTL。
        """
        from core.redis_client import get_redis

        redis = await get_redis()
        assert type(redis).__name__ == "InMemoryRedis", "测试环境应走内存降级"

        token = await acquire_edit_lock(resume_id=99901, user_id=100)
        assert token is not None
        assert await is_edit_locked(99901) is True

        # 连续续期多次，锁必须一直存在
        for _ in range(3):
            ok = await renew_edit_lock(resume_id=99901, user_id=100, lock_token=token)
            assert ok is True
            assert await is_edit_locked(99901) is True, "续期后锁不应丢失"

        # 错误 token 续期失败，且不破坏他人锁
        bad = await renew_edit_lock(resume_id=99901, user_id=100, lock_token="wrong")
        assert bad is False
        assert await is_edit_locked(99901) is True


# ═══════════════════════════════════════════════════════════════
# 2. 短事务写入测试
# ═══════════════════════════════════════════════════════════════


class TestShortTransaction:
    """短事务写入测试（_update_module_short_txn / _replace_all_modules_short_txn）。"""

    async def test_update_module_create_new(self, db_session, registered_user):
        """短事务新建模块（模块不存在时自动创建）。"""
        from services.react_agent.tools import _update_module_short_txn

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        with patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest):
            result = await _update_module_short_txn(
                registered_user["id"],
                resume.id,
                "skills",
                _VALID_SKILLS,
            )
        assert "已更新" in result

        # 验证写入
        from sqlalchemy import select
        from models.resume_module import ResumeModule

        mod_result = await db_session.execute(
            select(ResumeModule).where(
                ResumeModule.resume_id == resume.id,
                ResumeModule.module_type == "skills",
            )
        )
        module = mod_result.scalar_one_or_none()
        assert module is not None
        assert module.content["categories"][0]["name"] == "编程语言"

    async def test_update_module_existing(self, db_session, registered_user):
        """短事务更新现有模块。"""
        from services.react_agent.tools import _update_module_short_txn

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        new_content = {"name": "李四", "phone": "13900139000"}
        with patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest):
            result = await _update_module_short_txn(
                registered_user["id"],
                resume.id,
                "basic_info",
                new_content,
            )
        assert "已更新" in result

        # 验证更新（需 expire 已缓存的 ORM 对象，强制重新查询）
        from sqlalchemy import select
        from models.resume_module import ResumeModule

        resume_id = resume.id
        db_session.expire_all()
        mod_result = await db_session.execute(
            select(ResumeModule).where(
                ResumeModule.resume_id == resume_id,
                ResumeModule.module_type == "basic_info",
            )
        )
        module = mod_result.scalar_one_or_none()
        assert module.content["name"] == "李四"

    async def test_update_module_invalid_content(self, db_session, registered_user):
        """无效 content（缺必填字段）→ 抛 ToolRetryError（A3 回灌自愈）。"""
        from services.react_agent.tools import _update_module_short_txn

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        # basic_info 必须有 name 字段
        invalid_content = {"phone": "13800138000"}
        with pytest.raises(ToolRetryError) as exc_info:
            await _update_module_short_txn(
                registered_user["id"],
                resume.id,
                "basic_info",
                invalid_content,
            )
        err = str(exc_info.value)
        assert "校验失败" in err
        # 结构化逐字段错误：明确指出缺失的 name 字段
        assert "name" in err

    async def test_update_module_wrong_user(self, db_session, registered_user):
        """非本人简历 → 失败。"""
        from services.react_agent.tools import _update_module_short_txn

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        with patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest):
            result = await _update_module_short_txn(
                99999,
                resume.id,
                "basic_info",
                _VALID_BASIC_INFO,
            )
        assert "不存在" in result or "无权" in result

    async def test_replace_all_modules(self, db_session, registered_user):
        """短事务全量替换所有模块。"""
        from services.react_agent.tools import _replace_all_modules_short_txn

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        new_modules = [
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "education", "content": _VALID_EDUCATION, "sort_order": 1},
            {"module_type": "skills", "content": _VALID_SKILLS, "sort_order": 2},
        ]

        with patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest):
            result = await _replace_all_modules_short_txn(
                registered_user["id"],
                resume.id,
                new_modules,
            )
        assert "重写" in result
        assert "3" in result

        # 验证模块数
        from sqlalchemy import select
        from models.resume_module import ResumeModule

        resume_id = resume.id
        db_session.expire_all()
        mod_result = await db_session.execute(
            select(ResumeModule).where(ResumeModule.resume_id == resume_id)
        )
        modules = list(mod_result.scalars().all())
        assert len(modules) == 3

    async def test_replace_all_modules_invalid(self, db_session, registered_user):
        """全量替换含无效模块（缺必填字段）→ 抛 ToolRetryError。"""
        from services.react_agent.tools import _replace_all_modules_short_txn

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        bad_modules = [
            {"module_type": "basic_info", "content": {"phone": "123"}, "sort_order": 0},
        ]

        with pytest.raises(ToolRetryError) as exc_info:
            await _replace_all_modules_short_txn(
                registered_user["id"],
                resume.id,
                bad_modules,
            )
        err = str(exc_info.value)
        assert "校验失败" in err
        assert "name" in err


# ═══════════════════════════════════════════════════════════════
# 3. generate_module 工具测试
# ═══════════════════════════════════════════════════════════════


class TestGenerateModuleTool:
    """generate_module 工具测试（mock llm_generate_with_tools）。"""

    async def test_generate_module_success(self, db_session, registered_user):
        """正常生成模块 → 模型通过 submit_module_content 提交 → 写入 DB。"""
        from services.react_agent.tools import GenerateModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        content = {"name": "王五", "phone": "13700137000", "email": "wangwu@example.com"}

        tool = GenerateModuleTool(db=db_session, user_id=registered_user["id"])
        with (
            patch(
                "services.react_agent.tools.llm_generate_with_tools",
                new_callable=AsyncMock,
                return_value=_tool_resp("submit_module_content", content),
            ),
            patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest),
        ):
            result = await tool._execute(
                resume_id=resume.id,
                module_type="basic_info",
                prompt="",
            )

        assert "已更新" in result

    async def test_generate_module_invalid_type(self, db_session, registered_user):
        """无效 module_type → 报错。"""
        from services.react_agent.tools import GenerateModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = GenerateModuleTool(db=db_session, user_id=registered_user["id"])
        result = await tool._execute(
            resume_id=resume.id,
            module_type="invalid_type",
            prompt="",
        )
        assert "未知" in result

    async def test_generate_module_no_tool_call(self, db_session, registered_user):
        """模型未调用工具 → 报错。"""
        from services.react_agent.tools import GenerateModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = GenerateModuleTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate_with_tools",
            new_callable=AsyncMock,
            return_value=LLMToolResponse(content="", tool_calls=[]),
        ):
            with pytest.raises(ToolRetryError) as exc_info:
                await tool._execute(
                    resume_id=resume.id,
                    module_type="basic_info",
                    prompt="",
                )
        assert "未通过工具提交" in str(exc_info.value)

    async def test_generate_module_invalid_args_json(self, db_session, registered_user):
        """工具参数非法 JSON → 抛 ToolRetryError（A3 回灌自愈）。"""
        from services.react_agent.tools import GenerateModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = GenerateModuleTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate_with_tools",
            new_callable=AsyncMock,
            return_value=LLMToolResponse(
                tool_calls=[
                    ToolCall(id="call_1", name="submit_module_content", arguments="{不是JSON}")
                ]
            ),
        ):
            with pytest.raises(ToolRetryError) as exc_info:
                await tool._execute(
                    resume_id=resume.id,
                    module_type="basic_info",
                    prompt="",
                )
        assert "JSON 解析失败" in str(exc_info.value)

    async def test_generate_module_wrong_tool_name(self, db_session, registered_user):
        """模型调用了非预期工具 → 抛 ToolRetryError（A3 回灌自愈）。"""
        from services.react_agent.tools import GenerateModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = GenerateModuleTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate_with_tools",
            new_callable=AsyncMock,
            return_value=_tool_resp("other_tool", {}),
        ):
            with pytest.raises(ToolRetryError) as exc_info:
                await tool._execute(
                    resume_id=resume.id,
                    module_type="basic_info",
                    prompt="",
                )
        assert "非预期工具" in str(exc_info.value)

    async def test_generate_module_content_validation_failed(self, db_session, registered_user):
        """模型提交的 content 缺必填字段 → 抛 ToolRetryError（中文逐字段 + 修复指引）。"""
        from services.react_agent.tools import GenerateModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        # basic_info 缺必填 name
        tool = GenerateModuleTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate_with_tools",
            new_callable=AsyncMock,
            return_value=_tool_resp("submit_module_content", {"phone": "123"}),
        ):
            with pytest.raises(ToolRetryError) as exc_info:
                await tool._execute(
                    resume_id=resume.id,
                    module_type="basic_info",
                    prompt="",
                )
        err = str(exc_info.value)
        assert "校验失败" in err
        assert "name" in err
        assert "必填" in err


# ═══════════════════════════════════════════════════════════════
# 4. check_module 工具测试
# ═══════════════════════════════════════════════════════════════


class TestCheckModuleTool:
    """check_module 工具测试（只读，mock LLM）。"""

    async def test_check_module_success(self, db_session, registered_user):
        """正常检查 → 返回 LLM 分析结果。"""
        from services.react_agent.tools import CheckModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        llm_response = "## 检查结果\n- 完整性: ✅\n- ATS兼容性: ✅\n\n## 改进建议\n1. 补充邮箱"

        tool = CheckModuleTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate",
            new_callable=AsyncMock,
            return_value=llm_response,
        ):
            result = await tool._execute(
                resume_id=resume.id,
                module_type="basic_info",
            )
        assert "检查结果" in result

    async def test_check_module_not_exist(self, db_session, registered_user):
        """模块不存在 → 提示先生成。"""
        from services.react_agent.tools import CheckModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = CheckModuleTool(db=db_session, user_id=registered_user["id"])
        result = await tool._execute(
            resume_id=resume.id,
            module_type="skills",
        )
        assert "不存在" in result


# ═══════════════════════════════════════════════════════════════
# 5. modify_module 工具测试
# ═══════════════════════════════════════════════════════════════


class TestModifyModuleTool:
    """modify_module 工具测试（mock LLM + 短事务写入）。"""

    async def test_modify_module_success(self, db_session, registered_user):
        """正常修改 → 模型通过 submit_modified_content 提交 → 写入 DB。"""
        from services.react_agent.tools import ModifyModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        modified_content = {"name": "张三", "phone": "13800138000", "email": "new@example.com"}

        tool = ModifyModuleTool(db=db_session, user_id=registered_user["id"])
        with (
            patch(
                "services.react_agent.tools.llm_generate_with_tools",
                new_callable=AsyncMock,
                return_value=_tool_resp("submit_modified_content", modified_content),
            ),
            patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest),
        ):
            result = await tool._execute(
                resume_id=resume.id,
                module_type="basic_info",
                instruction="把邮箱改为 new@example.com",
            )
        assert "已更新" in result

    async def test_modify_module_not_exist(self, db_session, registered_user):
        """模块不存在 → 提示先生成。"""
        from services.react_agent.tools import ModifyModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = ModifyModuleTool(db=db_session, user_id=registered_user["id"])
        result = await tool._execute(
            resume_id=resume.id,
            module_type="skills",
            instruction="添加 Python 技能",
        )
        assert "不存在" in result

    async def test_modify_module_no_tool_call(self, db_session, registered_user):
        """模型未调用工具 → 报错。"""
        from services.react_agent.tools import ModifyModuleTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = ModifyModuleTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate_with_tools",
            new_callable=AsyncMock,
            return_value=LLMToolResponse(content="", tool_calls=[]),
        ):
            with pytest.raises(ToolRetryError) as exc_info:
                await tool._execute(
                    resume_id=resume.id,
                    module_type="basic_info",
                    instruction="修改名字",
                )
        assert "未通过工具提交" in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════
# 6. rewrite_resume 工具测试
# ═══════════════════════════════════════════════════════════════


class TestRewriteResumeTool:
    """rewrite_resume 工具测试（mock llm_generate_with_tools + 全量替换）。"""

    async def test_rewrite_generate_mode(self, db_session, registered_user):
        """generate 模式 → 模型提交模块数组 → 全量写入。"""
        from services.react_agent.tools import RewriteResumeTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        modules = [
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "education", "content": _VALID_EDUCATION, "sort_order": 1},
            {"module_type": "work_experience", "content": _VALID_WORK, "sort_order": 2},
            {"module_type": "skills", "content": _VALID_SKILLS, "sort_order": 3},
        ]

        tool = RewriteResumeTool(db=db_session, user_id=registered_user["id"])
        with (
            patch(
                "services.react_agent.tools.llm_generate_with_tools",
                new_callable=AsyncMock,
                return_value=_tool_resp("submit_rewritten_resume", {"modules": modules}),
            ),
            patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest),
        ):
            result = await tool._execute(
                resume_id=resume.id,
                mode="generate",
                target_position="Python 后端开发",
            )
        assert "重写" in result
        assert "4" in result

    async def test_rewrite_optimize_mode(self, db_session, registered_user):
        """optimize 模式 → 模型优化现有内容。"""
        from services.react_agent.tools import RewriteResumeTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        modules = [
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "skills", "content": _VALID_SKILLS, "sort_order": 1},
        ]

        tool = RewriteResumeTool(db=db_session, user_id=registered_user["id"])
        with (
            patch(
                "services.react_agent.tools.llm_generate_with_tools",
                new_callable=AsyncMock,
                return_value=_tool_resp("submit_rewritten_resume", {"modules": modules}),
            ),
            patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest),
        ):
            result = await tool._execute(
                resume_id=resume.id,
                mode="optimize",
                target_position="Python 后端开发",
            )
        assert "重写" in result

    async def test_rewrite_no_tool_call(self, db_session, registered_user):
        """模型未调用工具 → 报错。"""
        from services.react_agent.tools import RewriteResumeTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = RewriteResumeTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate_with_tools",
            new_callable=AsyncMock,
            return_value=LLMToolResponse(content="", tool_calls=[]),
        ):
            with pytest.raises(ToolRetryError) as exc_info:
                await tool._execute(
                    resume_id=resume.id,
                    mode="generate",
                    target_position=None,
                )
        assert "未通过工具提交" in str(exc_info.value)

    async def test_rewrite_invalid_args_json(self, db_session, registered_user):
        """工具参数非法 JSON → 报错。"""
        from services.react_agent.tools import RewriteResumeTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = RewriteResumeTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate_with_tools",
            new_callable=AsyncMock,
            return_value=LLMToolResponse(
                tool_calls=[
                    ToolCall(id="call_1", name="submit_rewritten_resume", arguments="{不是JSON}")
                ]
            ),
        ):
            with pytest.raises(ToolRetryError) as exc_info:
                await tool._execute(
                    resume_id=resume.id,
                    mode="generate",
                    target_position=None,
                )
        assert "JSON 解析失败" in str(exc_info.value)

    async def test_rewrite_invalid_module_skipped(self, db_session, registered_user):
        """部分模块校验失败 → 有效模块仍然写入。"""
        from services.react_agent.tools import RewriteResumeTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        modules = [
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "basic_info", "content": {"phone": "123"}, "sort_order": 1},  # 缺 name
            {"module_type": "skills", "content": _VALID_SKILLS, "sort_order": 2},
        ]

        tool = RewriteResumeTool(db=db_session, user_id=registered_user["id"])
        with (
            patch(
                "services.react_agent.tools.llm_generate_with_tools",
                new_callable=AsyncMock,
                return_value=_tool_resp("submit_rewritten_resume", {"modules": modules}),
            ),
            patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest),
        ):
            result = await tool._execute(
                resume_id=resume.id,
                mode="generate",
                target_position=None,
            )
        # 应该写入 2 个有效模块（basic_info 和 skills），跳过 1 个无效的
        assert "重写" in result
        assert "校验失败" in result or "跳过" in result

    async def test_rewrite_all_invalid(self, db_session, registered_user):
        """全部模块校验失败 → 报错。"""
        from services.react_agent.tools import RewriteResumeTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        modules = [
            {"module_type": "basic_info", "content": {"phone": "123"}, "sort_order": 0},
        ]

        tool = RewriteResumeTool(db=db_session, user_id=registered_user["id"])
        with (
            patch(
                "services.react_agent.tools.llm_generate_with_tools",
                new_callable=AsyncMock,
                return_value=_tool_resp("submit_rewritten_resume", {"modules": modules}),
            ),
            patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest),
        ):
            with pytest.raises(ToolRetryError) as exc_info:
                await tool._execute(
                    resume_id=resume.id,
                    mode="generate",
                    target_position=None,
                )
        assert "无有效" in str(exc_info.value) or "校验失败" in str(exc_info.value)

    async def test_rewrite_missing_modules_key(self, db_session, registered_user):
        """模型提交的参数缺 modules 数组 → 报错。"""
        from services.react_agent.tools import RewriteResumeTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        tool = RewriteResumeTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate_with_tools",
            new_callable=AsyncMock,
            return_value=_tool_resp("submit_rewritten_resume", {}),
        ):
            with pytest.raises(ToolRetryError) as exc_info:
                await tool._execute(
                    resume_id=resume.id,
                    mode="generate",
                    target_position=None,
                )
        assert "modules 应为数组" in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════
# 7. ask_info 工具测试
# ═══════════════════════════════════════════════════════════════


class TestAskInfoTool:
    """ask_info 工具测试（只读，mock LLM）。"""

    async def test_ask_info_success(self, db_session, registered_user):
        """正常追问 → 返回 LLM 建议。"""
        from services.react_agent.tools import AskInfoTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        llm_response = (
            "1. 你的简历缺少工作经历，建议补充\n"
            "2. 高优先级：添加至少一段工作或实习经历\n"
            "3. 中优先级：补充项目经历"
        )

        tool = AskInfoTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate",
            new_callable=AsyncMock,
            return_value=llm_response,
        ):
            result = await tool._execute(
                resume_id=resume.id,
                question="我的简历还缺什么？",
            )
        assert "工作经历" in result or "优先级" in result

    async def test_ask_info_empty_resume(self, db_session, registered_user):
        """空简历追问 → 仍然返回建议。"""
        from services.react_agent.tools import AskInfoTool
        from schemas.resume_module import BuilderCreateRequest
        from services.resume_builder import create_builder_resume

        body = BuilderCreateRequest(filename="空简历", modules=[])
        resume, _ = await create_builder_resume(db_session, registered_user["id"], body)

        llm_response = "建议先填写基本信息（姓名、联系方式）"

        tool = AskInfoTool(db=db_session, user_id=registered_user["id"])
        with patch(
            "services.react_agent.tools.llm_generate",
            new_callable=AsyncMock,
            return_value=llm_response,
        ):
            result = await tool._execute(
                resume_id=resume.id,
                question="应该从哪里开始？",
            )
        assert "基本信息" in result


# ═══════════════════════════════════════════════════════════════
# 8. 工具注册表完整性回归测试
# ═══════════════════════════════════════════════════════════════


class TestBuilderToolsRegistry:
    """Builder 工具注册表回归测试。"""

    def test_builder_tools_implemented(self):
        """5 个 builder 工具不再是骨架占位。"""
        from services.react_agent.tools import (
            GenerateModuleTool,
            CheckModuleTool,
            ModifyModuleTool,
            RewriteResumeTool,
            AskInfoTool,
        )

        for tool_class in [
            GenerateModuleTool,
            CheckModuleTool,
            ModifyModuleTool,
            RewriteResumeTool,
            AskInfoTool,
        ]:
            assert tool_class.name != ""
            assert tool_class.description != ""
            assert tool_class.category == "builder"

    def test_builder_schemas_count(self):
        """get_builder_schemas() 返回 5 个 schema。"""
        from services.react_agent.tools import get_builder_schemas

        schemas = get_builder_schemas()
        assert len(schemas) == 5

    def test_builder_tool_names(self):
        """5 个 builder 工具名称正确。"""
        from services.react_agent.tools import (
            GenerateModuleTool,
            CheckModuleTool,
            ModifyModuleTool,
            RewriteResumeTool,
            AskInfoTool,
        )

        names = [
            GenerateModuleTool.name,
            CheckModuleTool.name,
            ModifyModuleTool.name,
            RewriteResumeTool.name,
            AskInfoTool.name,
        ]
        assert names == [
            "generate_module",
            "check_module",
            "modify_module",
            "rewrite_resume",
            "ask_info",
        ]


# ═══════════════════════════════════════════════════════════════
# 9. QA 改写工具写模块草稿
# ═══════════════════════════════════════════════════════════════


class TestQAWriteToModules:
    """rewrite_star/translate 整份重写为模块草稿 + 多轮累积不新建简历。"""

    async def test_rewrite_star_writes_modules_and_keeps_resume(self, db_session, registered_user):
        """rewrite_star 写模块落库 + Resume 行数不变（多轮累积保证）。"""
        from sqlalchemy import func, select
        from models.resume import Resume
        from models.resume_module import ResumeModule
        from services.react_agent.tools import RewriteStarTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])
        before = (await db_session.execute(select(func.count()).select_from(Resume))).scalar_one()

        modules = [
            {"module_type": "basic_info", "content": _VALID_BASIC_INFO, "sort_order": 0},
            {"module_type": "work_experience", "content": _VALID_WORK, "sort_order": 1},
            {"module_type": "skills", "content": _VALID_SKILLS, "sort_order": 2},
        ]
        tool = RewriteStarTool(db=db_session, user_id=registered_user["id"])
        with (
            patch(
                "services.react_agent.tools.llm_generate_with_tools",
                new_callable=AsyncMock,
                return_value=_tool_resp("submit_rewritten_resume", {"modules": modules}),
            ),
            patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest),
        ):
            result = await tool._execute(resume_id=resume.id, target_position="Python 后端")

        assert "重写" in result
        after = (await db_session.execute(select(func.count()).select_from(Resume))).scalar_one()
        assert after == before  # 不新建简历
        mods = (
            (
                await db_session.execute(
                    select(ResumeModule).where(ResumeModule.resume_id == resume.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(mods) == 3  # 模块已全量落库

    async def test_translate_writes_modules(self, db_session, registered_user):
        """translate 整份翻译 → 模块落库。"""
        from models.resume_module import ResumeModule
        from sqlalchemy import select
        from services.react_agent.tools import TranslateTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        modules = [
            {
                "module_type": "basic_info",
                "content": {"name": "Zhang San", "phone": "13800138000"},
                "sort_order": 0,
            },
            {
                "module_type": "skills",
                "content": {"categories": [{"name": "Languages", "items": ["Python"]}]},
                "sort_order": 1,
            },
        ]
        tool = TranslateTool(db=db_session, user_id=registered_user["id"])
        with (
            patch(
                "services.react_agent.tools.llm_generate_with_tools",
                new_callable=AsyncMock,
                return_value=_tool_resp("submit_rewritten_resume", {"modules": modules}),
            ),
            patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest),
        ):
            result = await tool._execute(resume_id=resume.id, target_lang="en")

        assert "重写" in result
        mods = (
            (
                await db_session.execute(
                    select(ResumeModule).where(ResumeModule.resume_id == resume.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(mods) == 2

    async def test_rewrite_star_skips_overlong_content(self, db_session, registered_user):
        """content 超长（如 summary>500）→ 该模块跳过并提示。"""
        from models.resume_module import ResumeModule
        from sqlalchemy import select
        from services.react_agent.tools import RewriteStarTool

        resume, _ = await _create_test_resume(db_session, registered_user["id"])

        # basic_info.summary 超长（>500）→ 校验失败跳过；skills 有效 → 写入
        modules = [
            {
                "module_type": "basic_info",
                "content": {"name": "张三", "summary": "长" * 501},
                "sort_order": 0,
            },
            {"module_type": "skills", "content": _VALID_SKILLS, "sort_order": 1},
        ]
        tool = RewriteStarTool(db=db_session, user_id=registered_user["id"])
        with (
            patch(
                "services.react_agent.tools.llm_generate_with_tools",
                new_callable=AsyncMock,
                return_value=_tool_resp("submit_rewritten_resume", {"modules": modules}),
            ),
            patch("services.react_agent.tools.AsyncSessionLocal", AsyncSessionTest),
        ):
            result = await tool._execute(resume_id=resume.id, target_position="后端")

        assert "校验失败" in result or "跳过" in result
        mods = (
            (
                await db_session.execute(
                    select(ResumeModule).where(ResumeModule.resume_id == resume.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(mods) == 1  # 只有有效的 skills 写入
