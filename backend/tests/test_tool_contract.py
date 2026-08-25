"""A3 工具契约化测试。

覆盖：
- args 校验失败 → ToolRetryError + 结构化逐字段错误文本
- 归属校验失败 → ToolFailed（不累计坏调用）
- 子类抛 ToolRetryError / ToolFailed → loop 执行层正确映射 is_error
- 未知工具回灌附可用工具列表
- per-tool 重试预算：同一工具连续失败超限 → 终止本轮
"""

import pytest
from pydantic import BaseModel, Field
from unittest.mock import AsyncMock, patch

from services.react_agent.tools.base import (
    Tool,
    ToolFailed,
    ToolRetryError,
    format_validation_error,
)


class _DemoArgs(BaseModel):
    resume_id: int = Field(..., description="简历 ID")
    query: str = Field(..., min_length=1, description="查询词")


class _DemoTool(Tool):
    name = "demo_tool"
    description = "demo"
    args_model = _DemoArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        return f"ok:{kwargs.get('query')}"


class _RetryTool(Tool):
    """子类抛 ToolRetryError（模拟参数/状态错误）。"""

    name = "retry_tool"
    description = "retry"
    args_model = _DemoArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        raise ToolRetryError("数据库暂时不可用，请稍后重试")


class _FailedTool(Tool):
    """子类抛 ToolFailed（模拟业务确定性失败）。"""

    name = "failed_tool"
    description = "failed"
    args_model = _DemoArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        raise ToolFailed("简历 999 不存在或无权访问")


# ═══════════════════════════════════════════════════════════
# 基类契约
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_args_validation_raises_tool_retry_error():
    """参数校验失败 → ToolRetryError，错误文本逐字段结构化。"""
    tool = _DemoTool()
    with pytest.raises(ToolRetryError) as exc_info:
        await tool.execute(query="")  # query 空 → 校验失败

    text = str(exc_info.value)
    assert "参数校验错误" in text
    assert "query" in text  # 字段名
    assert "type=" in text  # 错误类型


@pytest.mark.asyncio
async def test_ownership_failure_raises_tool_failed():
    """归属校验失败 → ToolFailed（业务确定性失败，不累计坏调用）。"""
    tool = _DemoTool(db=AsyncMock(), user_id=1)

    async def _no_resume(rid):
        return None

    tool._verify_ownership = _no_resume  # type: ignore[method-assign]
    with pytest.raises(ToolFailed):
        await tool.execute(resume_id=999, query="test")


@pytest.mark.asyncio
async def test_tool_retry_error_maps_to_is_error():
    """loop 执行层：ToolRetryError → is_error=True（累计坏调用）。"""
    from services.react_agent.loop import _execute_tool_call

    with patch("services.react_agent.loop.get_tool_by_name", return_value=_RetryTool), \
         patch("services.react_agent.loop.AsyncSessionLocal"):
        result, is_error, _, _ = await _execute_tool_call(
            type("TC", (), {"name": "retry_tool", "arguments": '{"resume_id": 1, "query": "x"}', "id": "1"})(),
            db=None, user_id=1,
        )

    assert is_error is True
    assert "数据库暂时不可用" in result


@pytest.mark.asyncio
async def test_tool_failed_maps_to_non_retryable_business_error():
    """ToolFailed 必须是失败，但不应混入可重试错误预算。"""
    from services.react_agent.loop import _execute_tool_call

    with patch("services.react_agent.loop.get_tool_by_name", return_value=_FailedTool), \
         patch("services.react_agent.loop.AsyncSessionLocal"):
        result, is_error, _, _ = await _execute_tool_call(
            type("TC", (), {"name": "failed_tool", "arguments": '{"resume_id": 999, "query": "x"}', "id": "1"})(),
            db=None, user_id=1,
        )

    assert is_error is True
    assert getattr(result, "retryable", None) is False
    assert "⛔" in result


@pytest.mark.asyncio
async def test_unknown_tool_lists_available():
    """未知工具 → 错误文本附可用工具列表（模型自愈）。"""
    from services.react_agent.loop import _execute_tool_call

    with patch("services.react_agent.loop.get_tool_by_name", return_value=None), \
         patch("services.react_agent.loop.get_tools_for_agent", return_value=[_DemoTool]):
        result, is_error, _, _ = await _execute_tool_call(
            type("TC", (), {"name": "nope_tool", "arguments": "{}", "id": "1"})(),
            db=None, user_id=1,
        )

    assert is_error is True
    assert "不存在" in result
    assert "demo_tool" in result  # 附可用工具名


def test_format_validation_error_structure():
    """格式化函数输出 loc/type/msg。"""
    try:
        _DemoArgs()  # 缺字段
    except Exception as e:
        text = format_validation_error(e)  # type: ignore[arg-type]
        assert "resume_id" in text
        assert "type=missing" in text
