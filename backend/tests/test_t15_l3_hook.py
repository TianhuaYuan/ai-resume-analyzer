"""T15: L3 画像构建钩子 — ready 转换共享点，双路径。

测试范围：
- build_l3_profile_background: 后台构建 summary + skills 画像
- 只调 2 种分析类型（不调全量 4 种）
- 错误不外抛（不影响主流程）
- 共享函数可被上传路径和 builder 路径复用
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.react_agent.memory import build_l3_profile_background


# ═══════════════════════════════════════════════════════════════
# build_l3_profile_background
# ═══════════════════════════════════════════════════════════════


class TestBuildL3Profile:
    """L3 画像后台构建：只调 summary + skills 两种。"""

    @pytest.mark.asyncio
    async def test_calls_summary_and_skills_only(self):
        """只调 analyze_resume 的 summary 和 skills 两种类型。"""
        with patch("services.react_agent.memory.AsyncSessionLocal") as mock_session_cls, \
             patch("services.react_agent.memory.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_analyze.return_value = {"analysis": "result"}

            await build_l3_profile_background(resume_id=10, user_id=1)

            # 验证调了 2 次
            assert mock_analyze.call_count == 2
            # 验证调的是 summary 和 skills
            called_types = [call.kwargs.get("analysis_type") for call in mock_analyze.call_args_list]
            assert "summary" in called_types
            assert "skills" in called_types
            # 不应该调 experience 或 score
            assert "experience" not in called_types
            assert "score" not in called_types

    @pytest.mark.asyncio
    async def test_does_not_raise_on_error(self):
        """analyze_resume 抛异常时不外抛，只记日志。"""
        with patch("services.react_agent.memory.AsyncSessionLocal") as mock_session_cls, \
             patch("services.react_agent.memory.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_analyze.side_effect = Exception("LLM 超时")

            # 不应该抛异常
            await build_l3_profile_background(resume_id=10, user_id=1)

    @pytest.mark.asyncio
    async def test_continues_on_partial_failure(self):
        """summary 失败后 skills 仍然继续尝试。"""
        with patch("services.react_agent.memory.AsyncSessionLocal") as mock_session_cls, \
             patch("services.react_agent.memory.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_analyze.side_effect = [Exception("summary 失败"), {"analysis": "skills ok"}]

            await build_l3_profile_background(resume_id=10, user_id=1)
            # 两次都尝试了
            assert mock_analyze.call_count == 2

    @pytest.mark.asyncio
    async def test_uses_independent_db_session(self):
        """使用独立的 AsyncSessionLocal，不依赖调用方的 session。"""
        with patch("services.react_agent.memory.AsyncSessionLocal") as mock_session_cls, \
             patch("services.react_agent.memory.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_analyze.return_value = {"analysis": "ok"}

            await build_l3_profile_background(resume_id=10, user_id=1)

            # 验证用了独立 session
            mock_session_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_resume_id_and_user_id(self):
        """正确传递 resume_id 和 user_id 到 analyze_resume。"""
        with patch("services.react_agent.memory.AsyncSessionLocal") as mock_session_cls, \
             patch("services.react_agent.memory.analyze_resume", new_callable=AsyncMock) as mock_analyze:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_analyze.return_value = {"analysis": "ok"}

            await build_l3_profile_background(resume_id=42, user_id=7)

            for call in mock_analyze.call_args_list:
                assert call.kwargs.get("resume_id") == 42
                assert call.kwargs.get("user_id") == 7


# ═══════════════════════════════════════════════════════════════
# 集成：ready 转换共享点
# ═══════════════════════════════════════════════════════════════


class TestReadyTransitionHook:
    """ready 转换时触发 L3 画像构建（上传路径）。"""

    @pytest.mark.asyncio
    async def test_process_resume_background_triggers_l3(self):
        """process_resume_background 完成 ready 转换后触发 build_l3_profile_background。"""
        with patch("services.resume_service.AsyncSessionLocal") as mock_session_cls, \
             patch("services.resume_service.parse_resume") as mock_parse, \
             patch("services.resume_service.process_resume", new_callable=AsyncMock) as mock_process, \
             patch("services.resume_analyze_producer.publish_analyze_task", new_callable=AsyncMock) as mock_publish, \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock) as mock_build_l3:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_parse.return_value = "parsed text"
            mock_process.return_value = 5

            from services.resume_service import process_resume_background
            await process_resume_background(resume_id=1, file_path="/test.pdf", user_id=10)

            # 验证 L3 画像构建被调用
            mock_build_l3.assert_awaited_once_with(resume_id=1, user_id=10)

    @pytest.mark.asyncio
    async def test_l3_failure_does_not_break_processing(self):
        """L3 画像构建失败不影响简历处理主流程。"""
        with patch("services.resume_service.AsyncSessionLocal") as mock_session_cls, \
             patch("services.resume_service.parse_resume") as mock_parse, \
             patch("services.resume_service.process_resume", new_callable=AsyncMock) as mock_process, \
             patch("services.resume_analyze_producer.publish_analyze_task", new_callable=AsyncMock) as mock_publish, \
             patch("services.react_agent.memory.build_l3_profile_background", new_callable=AsyncMock) as mock_build_l3:
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_parse.return_value = "parsed text"
            mock_process.return_value = 5
            mock_build_l3.side_effect = Exception("L3 构建失败")

            from services.resume_service import process_resume_background
            # 不应该抛异常
            await process_resume_background(resume_id=1, file_path="/test.pdf", user_id=10)

            # 验证 resume 状态仍是 ready（L3 失败不影响）
            # mock_db.execute 应该被调用了 ready 更新
            assert mock_db.execute.call_count >= 1
