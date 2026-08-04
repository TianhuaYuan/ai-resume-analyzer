"""问答 → L4 长期记忆回流 单测。

覆盖 save_qa_to_memory 的筛选与调用：
- 有信息量的问答（非拒答 + 答案够长）→ 触发 save_memory（snippet/memory_type/importance 正确）
- 拒答话术 → 不触发
- 短答案 → 不触发
- 空 question / answer → 不触发
- save_memory 异常 → 不抛，返回 False（失败不阻断问答主流程）

mock 方式：save_qa_to_memory 内部惰性导入
``from services.memory.memory_store import save_memory``，因此 patch
``services.memory.memory_store.save_memory`` 即可拦截。
"""

from unittest.mock import AsyncMock, patch

from services.qa_service import (
    QA_MEMORY_IMPORTANCE,
    is_informative_qa,
    save_qa_to_memory,
)

_INFORMATIVE_Q = "请分析我的职业规划应该怎么调整"
_INFORMATIVE_A = (
    "根据你的简历，你在后端开发方向有扎实的项目经验，三个项目都涉及分布式系统设计，"
    "其中秒杀系统的限流与降级方案体现出你对高并发场景有实践积累。结合你的意向岗位，"
    "建议优先投递后端研发岗，并补充消息队列的进阶实践以匹配目标职级。"
)
_REJECT_A = "抱歉，简历中未提及该信息。"


class TestIsInformativeQa:
    def test_long_non_reject_answer_is_informative(self):
        assert is_informative_qa(_INFORMATIVE_Q, _INFORMATIVE_A) is True

    def test_reject_phrase_is_not_informative(self):
        assert is_informative_qa(_INFORMATIVE_Q, _REJECT_A) is False

    def test_short_answer_is_not_informative(self):
        assert is_informative_qa(_INFORMATIVE_Q, "是的") is False

    def test_empty_answer_is_not_informative(self):
        assert is_informative_qa(_INFORMATIVE_Q, "") is False

    def test_empty_question_is_not_informative(self):
        assert is_informative_qa("", _INFORMATIVE_A) is False


class TestSaveQaToMemory:
    async def test_informative_qa_triggers_save_memory(self):
        with patch("services.memory.memory_store.save_memory", new=AsyncMock()) as mock_save:
            ok = await save_qa_to_memory(user_id=7, question=_INFORMATIVE_Q, answer=_INFORMATIVE_A)
        assert ok is True
        mock_save.assert_awaited_once()
        _, kwargs = mock_save.call_args
        assert kwargs["user_id"] == 7
        assert kwargs["memory_type"] == "semantic"
        assert kwargs["importance"] == QA_MEMORY_IMPORTANCE
        # snippet 形式：问答沉淀（问题前30）：答案前200
        assert kwargs["snippet"].startswith("问答沉淀（")
        assert "职业规划" in kwargs["snippet"]
        assert "后端开发" in kwargs["snippet"]

    async def test_reject_answer_skips_memory(self):
        with patch("services.memory.memory_store.save_memory", new=AsyncMock()) as mock_save:
            ok = await save_qa_to_memory(user_id=7, question=_INFORMATIVE_Q, answer=_REJECT_A)
        assert ok is False
        mock_save.assert_not_awaited()

    async def test_short_answer_skips_memory(self):
        with patch("services.memory.memory_store.save_memory", new=AsyncMock()) as mock_save:
            ok = await save_qa_to_memory(user_id=7, question=_INFORMATIVE_Q, answer="是的")
        assert ok is False
        mock_save.assert_not_awaited()

    async def test_save_memory_failure_is_suppressed(self):
        with patch(
            "services.memory.memory_store.save_memory",
            new=AsyncMock(side_effect=RuntimeError("vector store down")),
        ):
            # 失败不抛异常，返回 False（问答主流程不阻断）
            ok = await save_qa_to_memory(user_id=7, question=_INFORMATIVE_Q, answer=_INFORMATIVE_A)
        assert ok is False
