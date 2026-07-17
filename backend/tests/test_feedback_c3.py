"""C3: MCP analyze_resume sync lambda 传给 async with_retry → TypeError"""
import tempfile
import os
import pytest
from utils.file_parser import parse_resume
from core.retry import with_retry


@pytest.mark.asyncio
async def test_c3_parse_resume_with_retry_should_not_raise_typeerror():
    """with_retry 应该能正常调用 parse_resume 并返回 str，不应抛出 TypeError"""
    content = "Python is a programming language. " * 30
    with tempfile.NamedTemporaryFile(
        suffix=".txt", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        tmp_path = f.name

    try:
        # 正确行为：with_retry 应该能 await parse_resume 的结果
        # 当前 Bug：lambda 返回 str 而非 coroutine，await str → TypeError
        result = await with_retry(lambda: parse_resume(tmp_path), max_retries=0)
        assert isinstance(result, str), "parse_resume 应返回解析后的文本"
        assert len(result) > 0, "解析结果不应为空"
    finally:
        os.unlink(tmp_path)