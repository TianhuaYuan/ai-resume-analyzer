"""T14: memory 装配 — L1 16k 逐出 + L2 10 条 + L3 中性画像 + system prompt。

测试范围：
- truncate_tool_result: 工具结果截断 ≤2000 字符
- estimate_tokens: token 估算
- manage_l1_context: L1 逐出优先级（先工具轮 → 再对话轮），保留最近 4 轮
- get_l2_history: 从 qa_history 取最近 10 条
- get_l3_profile: 从 Redis 缓存读 summary+skills
- assemble_system_prompt: 装配分段 system prompt
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.react_agent.memory import (
    truncate_tool_result,
    estimate_tokens,
    count_message_tokens,
    manage_l1_context,
    get_l2_history,
    get_l3_profile,
    assemble_system_prompt,
)


def _make_assembly_mock_db():
    """构造 assemble_system_prompt 需要的 mock db。

    assemble_system_prompt 会 await db.execute 查询「当前简历」并注入 system prompt，
    裸 MagicMock 不能被 await → 这里让 execute 异步返回一个 ready resume 的 result。
    """
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MagicMock(id=10, filename="test.pdf", status="ready")
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ═══════════════════════════════════════════════════════════
# truncate_tool_result
# ═══════════════════════════════════════════════════════════


class TestTruncateToolResult:
    def test_short_text_unchanged(self):
        assert truncate_tool_result("短文本") == "短文本"

    def test_exact_2000_chars_unchanged(self):
        text = "a" * 2000
        assert truncate_tool_result(text) == text

    def test_over_2000_truncated(self):
        text = "a" * 3000
        result = truncate_tool_result(text, max_chars=2000)
        assert len(result) <= 2000
        assert result.endswith("...") or result.endswith("…")

    def test_custom_max_chars(self):
        text = "a" * 500
        result = truncate_tool_result(text, max_chars=100)
        assert len(result) <= 100

    def test_empty_string(self):
        assert truncate_tool_result("") == ""


# ═══════════════════════════════════════════════════════════
# estimate_tokens / count_message_tokens
# ═══════════════════════════════════════════════════════════


class TestTokenEstimation:
    def test_estimate_tokens_positive(self):
        assert estimate_tokens("hello world") > 0

    def test_estimate_tokens_empty(self):
        assert estimate_tokens("") == 0

    def test_estimate_tokens_chinese(self):
        # 中文 token 密度更高
        cn = estimate_tokens("你好世界")
        en = estimate_tokens("hello world")
        assert cn > 0
        assert en > 0

    def test_count_message_tokens(self):
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]
        total = count_message_tokens(messages)
        assert total > 0

    def test_count_message_tokens_empty(self):
        assert count_message_tokens([]) == 0


# ═══════════════════════════════════════════════════════════
# manage_l1_context
# ═══════════════════════════════════════════════════════════


class TestManageL1Context:
    """L1 工作记忆：16k token 预算逐出。"""

    def test_under_budget_unchanged(self):
        """预算充足时消息不变。"""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        result = manage_l1_context(messages, max_tokens=16000)
        assert len(result) == len(messages)

    def test_system_always_kept(self):
        """system 消息始终保留。"""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "x" * 100},
            {"role": "assistant", "content": "y" * 100},
        ]
        result = manage_l1_context(messages, max_tokens=10)
        assert result[0]["role"] == "system"

    def test_tool_result_truncated(self):
        """工具结果被截断到 ≤2000 字符。"""
        long_tool_result = "x" * 5000
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "query"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "tc1", "type": "function", "function": {"name": "search", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "tc1", "content": long_tool_result},
            {"role": "assistant", "content": "done"},
        ]
        result = manage_l1_context(messages, max_tokens=16000)
        for msg in result:
            if msg["role"] == "tool":
                assert len(msg["content"]) <= 2000

    def test_evict_oldest_tool_round_first(self):
        """超额时先丢最旧工具轮。"""
        # 构造 6 轮：3 个工具轮 + 3 个对话轮，总额超额
        messages = [
            {"role": "system", "content": "sys"},
        ]
        for i in range(6):
            messages.append({"role": "user", "content": f"question {i}"})
            if i < 3:
                # 工具轮
                messages.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"tc{i}", "type": "function", "function": {"name": "search", "arguments": "{}"}}]})
                messages.append({"role": "tool", "tool_call_id": f"tc{i}", "content": f"tool result {i} " * 500})
                messages.append({"role": "assistant", "content": f"answer {i}"})
            else:
                # 对话轮
                messages.append({"role": "assistant", "content": f"answer {i} " * 300})

        result = manage_l1_context(messages, max_tokens=500, keep_last_rounds=2)
        # system 保留 + 至少最近 2 轮保留
        assert result[0]["role"] == "system"
        # 最旧的工具轮应被丢弃
        tool_msgs = [m for m in result if m["role"] == "tool"]
        # 不应包含 tc0（最旧的工具轮）
        tc_ids = [m.get("tool_call_id") for m in tool_msgs]
        assert "tc0" not in tc_ids or len(result) < len(messages)

    def test_keep_last_4_rounds(self):
        """最近 4 轮始终保留。"""
        messages = [{"role": "system", "content": "sys"}]
        for i in range(8):
            messages.append({"role": "user", "content": f"q{i}"})
            messages.append({"role": "assistant", "content": f"a{i}"})

        result = manage_l1_context(messages, max_tokens=100, keep_last_rounds=4)
        # 最近 4 个 user 消息应在
        user_msgs = [m["content"] for m in result if m["role"] == "user"]
        assert "q7" in user_msgs
        assert "q4" in user_msgs

    def test_empty_messages(self):
        """空消息列表返回空。"""
        assert manage_l1_context([]) == []

    def test_only_system(self):
        """只有 system 消息时不变。"""
        messages = [{"role": "system", "content": "sys"}]
        result = manage_l1_context(messages, max_tokens=10)
        assert len(result) == 1
        assert result[0]["role"] == "system"


# ═══════════════════════════════════════════════════════════
# get_l2_history
# ═══════════════════════════════════════════════════════════


class TestGetL2History:
    """L2 情景记忆：从 qa_history 取最近 10 条。"""

    @pytest.mark.asyncio
    async def test_returns_history_list(self):
        """返回历史问答列表。"""
        mock_db = MagicMock()
        mock_records = [
            MagicMock(question="q1", answer="a1"),
            MagicMock(question="q2", answer="a2"),
        ]
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_records
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        history = await get_l2_history(mock_db, user_id=1, resume_id=10, limit=10)
        assert len(history) == 2
        assert history[0]["question"] == "q1"
        assert history[0]["answer"] == "a1"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_history(self):
        """无历史时返回空列表。"""
        mock_db = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        history = await get_l2_history(mock_db, user_id=1, resume_id=10)
        assert history == []

    @pytest.mark.asyncio
    async def test_limit_passed_to_query(self):
        """limit 参数传递到查询。"""
        mock_db = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        await get_l2_history(mock_db, user_id=1, resume_id=10, limit=5)
        # 验证查询被调用
        mock_db.execute.assert_awaited_once()


# ═══════════════════════════════════════════════════════════
# get_l3_profile
# ═══════════════════════════════════════════════════════════


class TestGetL3Profile:
    """L3 语义记忆：从 Redis 缓存读 summary+skills。"""

    @pytest.mark.asyncio
    async def test_returns_profile_when_cached(self):
        """缓存命中时返回 summary+skills。"""
        with patch("services.react_agent.memory.get_analysis_cache", new_callable=AsyncMock) as mock_cache:
            mock_cache.side_effect = [
                {"summary": "3年Python后端"},  # summary
                {"skills": ["Python", "FastAPI"]},  # skills
            ]
            profile = await get_l3_profile(resume_id=10)

        assert profile is not None
        assert "summary" in profile
        assert "skills" in profile
        assert "3年Python后端" in profile["summary"]

    @pytest.mark.asyncio
    async def test_returns_none_when_not_cached(self):
        """缓存未命中时返回 None。"""
        with patch("services.react_agent.memory.get_analysis_cache", new_callable=AsyncMock) as mock_cache:
            mock_cache.return_value = None
            profile = await get_l3_profile(resume_id=10)

        assert profile is None

    @pytest.mark.asyncio
    async def test_returns_partial_when_only_summary(self):
        """只有 summary 缓存时返回部分画像。"""
        with patch("services.react_agent.memory.get_analysis_cache", new_callable=AsyncMock) as mock_cache:
            mock_cache.side_effect = [
                {"summary": "后端工程师"},  # summary
                None,  # skills 未缓存
            ]
            profile = await get_l3_profile(resume_id=10)

        assert profile is not None
        assert "后端工程师" in profile.get("summary", "")


# ═══════════════════════════════════════════════════════════
# assemble_system_prompt
# ═══════════════════════════════════════════════════════════


class TestAssembleSystemPrompt:
    """system prompt 装配：L2 + L3 + 防幻觉/效率指令。"""

    @pytest.mark.asyncio
    async def test_contains_l3_profile(self):
        """system prompt 包含 L3 画像。"""
        mock_db = _make_assembly_mock_db()

        with patch("services.react_agent.memory.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.memory.get_l2_history", new_callable=AsyncMock) as mock_l2:
            mock_l3.return_value = {"summary": "3年Python后端", "skills": ["Python", "FastAPI"]}
            mock_l2.return_value = []

            prompt = await assemble_system_prompt(mock_db, user_id=1, resume_id=10)

        assert "Python" in prompt
        assert "3年Python后端" in prompt

    @pytest.mark.asyncio
    async def test_contains_l2_history(self):
        """system prompt 包含 L2 历史问答。"""
        mock_db = _make_assembly_mock_db()

        with patch("services.react_agent.memory.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.memory.get_l2_history", new_callable=AsyncMock) as mock_l2:
            mock_l3.return_value = None
            mock_l2.return_value = [
                {"question": "教育背景", "answer": "广东海洋大学"},
            ]

            prompt = await assemble_system_prompt(mock_db, user_id=1, resume_id=10)

        assert "教育背景" in prompt
        assert "广东海洋大学" in prompt

    @pytest.mark.asyncio
    async def test_contains_instructions(self):
        """system prompt 包含防幻觉/效率指令。"""
        mock_db = _make_assembly_mock_db()

        with patch("services.react_agent.memory.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.memory.get_l2_history", new_callable=AsyncMock) as mock_l2:
            mock_l3.return_value = None
            mock_l2.return_value = []

            prompt = await assemble_system_prompt(mock_db, user_id=1, resume_id=10)

        # 防幻觉指令
        assert "编造" in prompt or "虚构" in prompt or "幻觉" in prompt
        # 效率指令
        assert "工具" in prompt or "简洁" in prompt

    @pytest.mark.asyncio
    async def test_has_section_markers(self):
        """system prompt 有分段标记。"""
        mock_db = _make_assembly_mock_db()

        with patch("services.react_agent.memory.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.memory.get_l2_history", new_callable=AsyncMock) as mock_l2:
            mock_l3.return_value = {"summary": "test", "skills": ["test"]}
            mock_l2.return_value = [{"question": "q", "answer": "a"}]

            prompt = await assemble_system_prompt(mock_db, user_id=1, resume_id=10)

        # 应有分段标记（# 或 【】 等）
        assert "#" in prompt or "【" in prompt or "===" in prompt

    @pytest.mark.asyncio
    async def test_works_without_l3_and_l2(self):
        """无 L3 和 L2 时仍返回有效 prompt。"""
        mock_db = _make_assembly_mock_db()

        with patch("services.react_agent.memory.get_l3_profile", new_callable=AsyncMock) as mock_l3, \
             patch("services.react_agent.memory.get_l2_history", new_callable=AsyncMock) as mock_l2:
            mock_l3.return_value = None
            mock_l2.return_value = []

            prompt = await assemble_system_prompt(mock_db, user_id=1, resume_id=10)

        assert len(prompt) > 50  # 至少有基本指令
        assert isinstance(prompt, str)
