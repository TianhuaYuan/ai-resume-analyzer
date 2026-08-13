"""evaluate_node 假分数应标记 eval_forced。

原 bug：达到 max_retries 时返回 0.5 假分数，但无法与真实 0.5 分区分。
下游无法判断「评估真的打了 0.5 分」还是「没评估直接放行」。
"""
from unittest.mock import AsyncMock, patch

import pytest

from services.agentic_rag.generate import evaluate_node, _EVAL_MAX_RETRIES


@pytest.mark.asyncio
async def test_evaluate_max_retries_marks_eval_forced_true():
    """达到 max_retries 强制放行时，应返回 eval_forced=True。"""
    state = {
        "question": "测试问题",
        "rewritten_query": "改写后的问题",
        "answer": "这是一个有内容的答案",
        "sources": [{"text": "来源", "chunk_index": 0}],
        "search_round": _EVAL_MAX_RETRIES + 1,  # 超过最大重试次数
        "trace": {},
    }

    result = await evaluate_node(state)

    assert result.get("eval_forced") is True, (
        "max_retries 强制放行时应标记 eval_forced=True"
    )
    assert result["eval_score"] == 0.5
    assert result["should_retry"] is False


@pytest.mark.asyncio
async def test_evaluate_normal_marks_eval_forced_false():
    """正常 LLM 评估时，应返回 eval_forced=False。"""
    state = {
        "question": "测试问题",
        "rewritten_query": "改写后的问题",
        "answer": "这是一个有内容的答案",
        "sources": [{"text": "来源", "chunk_index": 0}],
        "search_round": 1,  # 未超过最大重试次数
        "trace": {},
    }

    # mock with_retry 返回有效评估 JSON
    mock_eval_json = '{"completeness": 7, "accuracy": 8, "source_credibility": 6, "feedback": "回答较完整"}'
    with patch(
        "services.agentic_rag.generate.with_retry",
        new_callable=AsyncMock,
        return_value=mock_eval_json,
    ):
        result = await evaluate_node(state)

    assert result.get("eval_forced") is False, (
        "正常评估时应标记 eval_forced=False"
    )
    # eval_score 应该是真实计算出来的复合分数，不是 0.5
    assert result["eval_score"] != 0.5 or result["eval_feedback"] != "已达最大重试次数"


@pytest.mark.asyncio
async def test_evaluate_no_answer_marks_eval_forced_false():
    """无答案跳过评估时，应返回 eval_forced=False（这不是强制放行，是拒绝）。"""
    state = {
        "question": "测试问题",
        "rewritten_query": "改写后的问题",
        "answer": "",  # 无答案
        "sources": [],
        "search_round": 0,
        "trace": {},
    }

    result = await evaluate_node(state)

    assert result.get("eval_forced") is False, (
        "无答案跳过评估时应标记 eval_forced=False（非强制放行）"
    )
    assert result["eval_score"] == 0.0
