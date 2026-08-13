"""T3: usage 统一记账 —— 全 LLM 调用点接入，只记成功，Redis 挂不阻塞。

测试范围：
- services/rag/usage.py record_llm_usage 核心逻辑
- pipeline.py llm_generate / _llm_generate_stream 接入
- analyze_service.py analyze_resume 接入
- match_jd_service.py match_jd 接入
"""

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════
# RED: usage.py 核心功能
# ═══════════════════════════════════════════════════════════


class TestRecordLlmUsage:
    """record_llm_usage 核心功能测试。"""

    @pytest.mark.asyncio
    async def test_records_four_counters(self):
        """正常调用时向 Redis 写入 prompt/completion/total/calls 四个计数器。"""
        from services.rag import usage as usage_mod

        mock_redis = AsyncMock()
        mock_redis.incrby = AsyncMock(return_value=100)
        mock_redis.expire = AsyncMock(return_value=True)

        with patch.object(usage_mod, "get_redis", return_value=mock_redis):
            await usage_mod.record_llm_usage(user_id=42, prompt_tokens=50, completion_tokens=30)

        # 验证写了 4 个计数器
        calls = mock_redis.incrby.call_args_list
        keys = [c.args[0] for c in calls]
        assert any("prompt" in k for k in keys)
        assert any("completion" in k for k in keys)
        assert any(":total" in k for k in keys)
        assert any("calls" in k for k in keys)

        # 验证数值正确
        prompt_call = next(c for c in calls if "prompt" in c.args[0])
        assert prompt_call.args[1] == 50

        total_call = next(c for c in calls if ":total" in c.args[0])
        assert total_call.args[1] == 80

    @pytest.mark.asyncio
    async def test_skips_when_zero_tokens(self):
        """prompt + completion = 0 时不写入 Redis。"""
        from services.rag import usage as usage_mod

        mock_redis = AsyncMock()

        with patch.object(usage_mod, "get_redis", return_value=mock_redis):
            await usage_mod.record_llm_usage(user_id=42, prompt_tokens=0, completion_tokens=0)

        mock_redis.incrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_negative_tokens(self):
        """负 token 不写入。"""
        from services.rag import usage as usage_mod

        mock_redis = AsyncMock()

        with patch.object(usage_mod, "get_redis", return_value=mock_redis):
            await usage_mod.record_llm_usage(user_id=42, prompt_tokens=-10, completion_tokens=5)

        mock_redis.incrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_block_on_redis_fail(self):
        """Redis 抛异常时不阻塞主流程、不抛异常。"""
        from services.rag import usage as usage_mod

        async def boom():
            raise RuntimeError("redis down")

        mock_redis = AsyncMock()
        mock_redis.incrby = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch.object(usage_mod, "get_redis", return_value=mock_redis):
            # 不应抛异常
            await usage_mod.record_llm_usage(user_id=42, prompt_tokens=10, completion_tokens=10)


# ═══════════════════════════════════════════════════════════
# RED: pipeline.py llm_generate 接入
# ═══════════════════════════════════════════════════════════


class TestLlmGenerateRecordsUsage:
    """llm_generate 传入 user_id 时记录 usage。"""

    @pytest.mark.asyncio
    async def test_records_when_user_id_given(self):
        """传入 user_id 时，成功后调用 record_llm_usage。"""
        from services.rag import pipeline as pipeline_mod

        mock_client = AsyncMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "hello"
        mock_completion.choices = [mock_choice]
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 20
        mock_usage.completion_tokens = 10
        mock_completion.usage = mock_usage
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        pipeline_mod.get_chat_client = lambda: mock_client

        with patch.object(pipeline_mod, "record_llm_usage", new_callable=AsyncMock) as mock_record:
            result = await pipeline_mod.llm_generate(
                "system", "user", user_id=99
            )

        assert result == "hello"
        mock_record.assert_awaited_once_with(
            99, 20, 10, model=ANY, scenario="field_rewrite"
        )

    @pytest.mark.asyncio
    async def test_no_record_without_user_id(self):
        """不传 user_id 时不记录 usage。"""
        from services.rag import pipeline as pipeline_mod

        mock_client = AsyncMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "hello"
        mock_completion.choices = [mock_choice]
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 20
        mock_usage.completion_tokens = 10
        mock_completion.usage = mock_usage
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        pipeline_mod.get_chat_client = lambda: mock_client

        with patch.object(pipeline_mod, "record_llm_usage", new_callable=AsyncMock) as mock_record:
            result = await pipeline_mod.llm_generate("system", "user")

        mock_record.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_record_on_failure(self):
        """LLM 调用失败时不记录 usage。"""
        from services.rag import pipeline as pipeline_mod

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API error"))
        pipeline_mod.get_chat_client = lambda: mock_client

        with patch.object(pipeline_mod, "record_llm_usage", new_callable=AsyncMock) as mock_record:
            with pytest.raises(RuntimeError):
                await pipeline_mod.llm_generate("system", "user", user_id=99)

        mock_record.assert_not_called()


# ═══════════════════════════════════════════════════════════
# RED: analyze_service.py 接入
# ═══════════════════════════════════════════════════════════


class TestAnalyzeResumeRecordsUsage:
    """analyze_resume 成功后记录 usage。"""

    @pytest.mark.asyncio
    async def test_records_usage_on_success(self):
        """analyze_resume 成功后调用 record_llm_usage。"""
        from services import analyze_service as svc

        with patch.object(svc, "get_analysis_cache", new_callable=AsyncMock, return_value=None), \
             patch.object(svc, "set_full_analysis_cache", new_callable=AsyncMock), \
             patch.object(svc, "get_chat_client") as mock_get_client, \
             patch.object(svc, "record_llm_usage", new_callable=AsyncMock) as mock_record:

            mock_client = AsyncMock()
            mock_completion = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "分析结果"
            mock_completion.choices = [mock_choice]
            mock_usage = MagicMock()
            mock_usage.prompt_tokens = 100
            mock_usage.completion_tokens = 50
            mock_completion.usage = mock_usage
            mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
            mock_get_client.return_value = mock_client

            # 需要 db 和 resume
            from unittest.mock import AsyncMock as MockAsync
            mock_db = MockAsync()
            mock_result = MagicMock()
            mock_resume = MagicMock()
            mock_resume.status = "ready"
            mock_resume.parsed_text = "简历内容"
            mock_result.scalar_one_or_none.return_value = mock_resume
            mock_db.execute = AsyncMock(return_value=mock_result)

            await svc.analyze_resume(mock_db, user_id=7, resume_id=1, analysis_type="summary")

        mock_record.assert_awaited_once_with(
            7, 100, 50, model=ANY, scenario="analysis:summary"
        )


# ═══════════════════════════════════════════════════════════
# RED: match_jd_service.py 接入
# ═══════════════════════════════════════════════════════════


class TestMatchJdRecordsUsage:
    """match_jd 成功后记录 usage。"""

    @pytest.mark.asyncio
    async def test_records_usage_via_llm_generate(self):
        """match_jd 调用 llm_generate 时传入 user_id，最终记录 usage。"""
        from services import match_jd_service as svc
        from services.rag import pipeline as pipeline_mod

        mock_client = AsyncMock()
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        # JSON-first 结构化匹配：返回合法 JSON → 只走一次 LLM 调用（不触发 markdown 降级）
        mock_choice.message.content = (
            '{"score": 85, "matched": ["Python"], "missing": ["Redis"], '
            '"gaps": ["学习 Redis"], "reason": "高度匹配"}'
        )
        mock_completion.choices = [mock_choice]
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 200
        mock_usage.completion_tokens = 80
        mock_completion.usage = mock_usage
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        pipeline_mod.get_chat_client = lambda: mock_client

        with patch.object(pipeline_mod, "record_llm_usage", new_callable=AsyncMock) as mock_record:
            from unittest.mock import AsyncMock as MockAsync
            mock_db = MockAsync()
            mock_result = MagicMock()
            mock_resume = MagicMock()
            mock_resume.status = "ready"
            mock_resume.parsed_text = "简历内容"
            mock_result.scalar_one_or_none.return_value = mock_resume
            mock_db.execute = AsyncMock(return_value=mock_result)

            await svc.match_jd(mock_db, user_id=8, resume_id=1, jd_text="JD内容")

        mock_record.assert_awaited_once_with(
            8, 200, 80, model=ANY, scenario="field_rewrite"
        )
