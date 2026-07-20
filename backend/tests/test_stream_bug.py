"""
测试流式 LLM 生成中的空 choices 问题（debugging 专用，后续并入 test_rag_service）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.rag.pipeline import _llm_generate_stream


class MockChunk:
    """模拟 OpenAI 流式 chunk"""

    def __init__(self, choices):
        self.choices = choices


class MockChoice:
    """模拟 choices[0]"""

    def __init__(self, content: str | None):
        self.delta = MagicMock()
        self.delta.content = content


def make_chunk(content: str | None = None):
    """构造一个有内容的 chunk"""
    return MockChunk(choices=[MockChoice(content=content)])


def make_empty_choices_chunk():
    """构造一个 choices 为空的 chunk（触发 bug 的关键）"""
    return MockChunk(choices=[])  # ← bug：空列表，choices[0] 抛 IndexError


@pytest.mark.asyncio
async def test_llm_generate_stream_skips_empty_choices():
    """
    RED-CAPABLE 反馈循环：
    当流式 API 返回 choices 为空的 chunk 时，_llm_generate_stream 应该跳过而不是崩溃。

    当前行为（有 bug）：抛 IndexError → 测试失败（红）
    修复后行为：优雅跳过 → 测试通过（绿）
    """
    # 构造流：正常 chunk → 空 choices → 正常 chunk
    chunks = [
        make_chunk("你好"),
        make_empty_choices_chunk(),  # ← bug 场景
        make_chunk("世界"),
    ]

    async def mock_stream():
        for c in chunks:
            yield c

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())

    with patch("services.rag.pipeline.get_chat_client", return_value=mock_client):
        collected = []
        async for token in _llm_generate_stream("system", "user"):
            collected.append(token)

    # 空 choices chunk 应该被跳过，不影响前后正常内容
    assert collected == ["你好", "世界"], (
        f"期望跳过空 choices chunk 得到 ['你好', '世界']，实际 {collected}"
    )


@pytest.mark.asyncio
async def test_rag_pipeline_handles_empty_choices_gracefully():
    """
    验证 RAG 全链路能优雅处理空 choices chunk：
    修复后不再崩溃，流式正常输出（无需 fallback）。
    """
    from services.rag.pipeline import ask_question_stream

    # 混合场景：正常 token → 空 choices（跳过） → 正常 token
    chunks = [
        make_chunk("你好"),
        make_empty_choices_chunk(),
        make_chunk("世界"),
    ]

    async def mock_stream():
        for c in chunks:
            yield c

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())

    patches = [
        patch("services.rag.pipeline.get_chat_client", return_value=mock_client),
        patch(
            "services.rag.pipeline.rewrite_query", new_callable=AsyncMock, return_value="测试问题"
        ),
        patch(
            "services.rag.pipeline.hybrid_search",
            new_callable=AsyncMock,
            return_value=[
                {
                    "chunk_index": 0,
                    "text": "一段简历内容",
                    "score": 0.8,
                    "source": "dense",
                    "section": "基本信息",
                },
            ],
        ),
        patch(
            "services.rag.pipeline.rerank",
            new_callable=AsyncMock,
            return_value=[
                {
                    "chunk_index": 0,
                    "text": "一段简历内容",
                    "rerank_score": 0.9,
                    "section": "基本信息",
                },
            ],
        ),
        patch("services.rag.pipeline.reject_if_low_score", return_value=False),
    ]

    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        results = []
        async for event in ask_question_stream(1, "测试问题"):
            if event["type"] in ("token", "done"):
                results.append(event)

        # 验证：空 choices 被跳过，前后正常内容合并输出
        token_texts = "".join(r["content"] for r in results if r["type"] == "token")
        # 应该包含完整的流式输出（空 choices 不影响）
        assert "你好" in token_texts
        assert "世界" in token_texts
