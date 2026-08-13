"""llm_generate_with_tools — tools + thinking + include_usage + delta 解析。

测试范围：
- 非流式：tools 返回 tool_calls / thinking 返回 reasoning_content / usage 记账 / JUDGE_MODEL
- 流式：token 事件 / tool_call delta 累积 / reasoning 分块 / usage 末 chunk / thinking 降级
- 归属：user_id 传入时记录 usage
"""

import json
from dataclasses import dataclass
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from services.rag.pipeline import (
    LLMToolResponse,
    ToolCall,
    llm_generate_with_tools,
    llm_generate_with_tools_stream,
)


# ═══════════════════════════════════════════════════════════
# Mock helpers — 模拟 OpenAI API 响应结构
# ═══════════════════════════════════════════════════════════


@dataclass
class MockFunction:
    name: str = ""
    arguments: str = ""


@dataclass
class MockToolCall:
    id: str = ""
    function: MockFunction = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.function is None:
            self.function = MockFunction()


@dataclass
class MockMessage:
    content: str | None = None
    tool_calls: list[MockToolCall] | None = None
    reasoning_content: str | None = None


@dataclass
class MockChoice:
    message: MockMessage = None  # type: ignore[assignment]
    delta: MockMessage = None  # type: ignore[assignment]
    finish_reason: str | None = None

    def __post_init__(self):
        if self.message is None:
            self.message = MockMessage()
        if self.delta is None:
            self.delta = MockMessage()


@dataclass
class MockUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class MockResponse:
    choices: list[MockChoice] = None  # type: ignore[assignment]
    usage: MockUsage | None = None

    def __post_init__(self):
        if self.choices is None:
            self.choices = []


@dataclass
class MockChunk:
    """流式单个 chunk。"""
    choices: list[MockChoice] = None  # type: ignore[assignment]
    usage: MockUsage | None = None

    def __post_init__(self):
        if self.choices is None:
            self.choices = []


class MockStream:
    """模拟 async iterator for streaming response。"""

    def __init__(self, chunks: list[MockChunk]):
        self._chunks = chunks

    def __aiter__(self):
        self._idx = 0
        return self

    async def __anext__(self):
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


def _make_chat_client_mock(response: MockResponse) -> MagicMock:
    """构造非流式 chat client mock。"""
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def _make_stream_client_mock(chunks: list[MockChunk]) -> MagicMock:
    """构造流式 chat client mock。"""
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=MockStream(chunks))
    return client


def _make_func_mock(name=None, arguments=""):
    """构造 function mock（MagicMock 的 name 是构造器保留参数，不能通过 kwargs 传入）。"""
    m = MagicMock()
    if name is not None:
        m.name = name
    m.arguments = arguments
    return m


# ═══════════════════════════════════════════════════════════
# 非流式测试
# ═══════════════════════════════════════════════════════════


class TestLLMGenerateWithToolsNonStream:
    """非流式 llm_generate_with_tools。"""

    @pytest.mark.asyncio
    async def test_returns_content_without_tools(self):
        """无 tools 时返回纯文本 content。"""
        resp = MockResponse(
            choices=[MockChoice(message=MockMessage(content="你好世界"))],
            usage=MockUsage(prompt_tokens=10, completion_tokens=5),
        )
        client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            result = await llm_generate_with_tools(
                messages=[{"role": "user", "content": "hello"}],
            )

        assert isinstance(result, LLMToolResponse)
        assert result.content == "你好世界"
        assert result.tool_calls == []
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 5

    @pytest.mark.asyncio
    async def test_returns_tool_calls(self):
        """有 tools 时返回 tool_calls。"""
        resp = MockResponse(
            choices=[
                MockChoice(
                    message=MockMessage(
                        content=None,
                        tool_calls=[
                            MockToolCall(
                                id="call_abc",
                                function=MockFunction(
                                    name="search_resume",
                                    arguments=json.dumps({"query": "教育背景"}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage=MockUsage(prompt_tokens=50, completion_tokens=20),
        )
        client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            result = await llm_generate_with_tools(
                messages=[{"role": "user", "content": "查教育背景"}],
                tools=[{"type": "function", "function": {"name": "search_resume"}}],
            )

        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert isinstance(tc, ToolCall)
        assert tc.id == "call_abc"
        assert tc.name == "search_resume"
        assert json.loads(tc.arguments) == {"query": "教育背景"}

    @pytest.mark.asyncio
    async def test_thinking_returns_reasoning_content(self):
        """thinking 开启时返回 reasoning_content。"""
        resp = MockResponse(
            choices=[
                MockChoice(
                    message=MockMessage(
                        content="答案是...",
                        reasoning_content="让我想想...",
                    )
                )
            ],
            usage=MockUsage(prompt_tokens=10, completion_tokens=5),
        )
        client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            result = await llm_generate_with_tools(
                messages=[{"role": "user", "content": "hello"}],
                thinking_enabled=True,
            )

        assert result.reasoning_content == "让我想想..."
        assert result.content == "答案是..."

    @pytest.mark.asyncio
    async def test_thinking_not_supported_degrades_gracefully(self):
        """模型不支持 thinking 时 reasoning_content 为 None，不报错。"""
        resp = MockResponse(
            choices=[
                MockChoice(
                    message=MockMessage(content="答案", reasoning_content=None)
                )
            ],
            usage=MockUsage(prompt_tokens=5, completion_tokens=3),
        )
        client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            result = await llm_generate_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                thinking_enabled=True,
            )

        assert result.reasoning_content is None
        assert result.content == "答案"

    @pytest.mark.asyncio
    async def test_records_usage_with_user_id(self):
        """user_id 传入时记录 usage。"""
        resp = MockResponse(
            choices=[MockChoice(message=MockMessage(content="ok"))],
            usage=MockUsage(prompt_tokens=100, completion_tokens=50),
        )
        client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            with patch("services.rag.pipeline.record_llm_usage", new_callable=AsyncMock) as mock_record:
                await llm_generate_with_tools(
                    messages=[{"role": "user", "content": "hi"}],
                    user_id=42,
                )

        mock_record.assert_awaited_once_with(
            42, 100, 50, model=ANY, scenario="tool_call"
        )

    @pytest.mark.asyncio
    async def test_no_usage_no_record(self):
        """response 无 usage 时不记账。"""
        resp = MockResponse(
            choices=[MockChoice(message=MockMessage(content="ok"))],
            usage=None,
        )
        client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            with patch("services.rag.pipeline.record_llm_usage", new_callable=AsyncMock) as mock_record:
                await llm_generate_with_tools(
                    messages=[{"role": "user", "content": "hi"}],
                    user_id=1,
                )

        mock_record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_judge_model(self):
        """model='judge' 时使用 JUDGE_MODEL + JUDGE 客户端。"""
        resp = MockResponse(
            choices=[MockChoice(message=MockMessage(content="judge result"))],
            usage=MockUsage(prompt_tokens=10, completion_tokens=5),
        )
        judge_client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_judge_client", return_value=judge_client):
            result = await llm_generate_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                model="judge",
            )

        assert result.content == "judge result"
        # 验证调用时传了 JUDGE_MODEL
        call_kwargs = judge_client.chat.completions.create.call_args.kwargs
        from core.config import settings
        assert call_kwargs["model"] == settings.JUDGE_MODEL

    @pytest.mark.asyncio
    async def test_temperature_and_max_tokens_passed(self):
        """temperature 和 max_tokens 正确传递。"""
        resp = MockResponse(
            choices=[MockChoice(message=MockMessage(content="ok"))],
            usage=MockUsage(),
        )
        client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            await llm_generate_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.7,
                max_tokens=500,
            )

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 500

    @pytest.mark.asyncio
    async def test_thinking_param_sent_when_enabled(self):
        """thinking_enabled=True 时请求体包含 thinking 参数。"""
        resp = MockResponse(
            choices=[MockChoice(message=MockMessage(content="ok"))],
            usage=MockUsage(),
        )
        client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            await llm_generate_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                thinking_enabled=True,
                thinking_effort="high",
            )

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"]["type"] == "enabled"
        assert call_kwargs["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_thinking_param_not_sent_when_disabled(self):
        """thinking_enabled=False 时请求体不含 thinking 参数。"""
        resp = MockResponse(
            choices=[MockChoice(message=MockMessage(content="ok"))],
            usage=MockUsage(),
        )
        client = _make_chat_client_mock(resp)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            await llm_generate_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                thinking_enabled=False,
            )

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"]["type"] == "disabled"
        assert "reasoning_effort" not in call_kwargs


# ═══════════════════════════════════════════════════════════
# 流式测试
# ═══════════════════════════════════════════════════════════


class TestLLMGenerateWithToolsStream:
    """流式 llm_generate_with_tools_stream。"""

    @pytest.mark.asyncio
    async def test_yields_token_events(self):
        """流式生成 token 事件。"""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockMessage(content="你好"))]),
            MockChunk(choices=[MockChoice(delta=MockMessage(content="世界"))]),
            MockChunk(choices=[], usage=MockUsage(prompt_tokens=5, completion_tokens=4)),
        ]
        client = _make_stream_client_mock(chunks)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            events = []
            async for event in llm_generate_with_tools_stream(
                messages=[{"role": "user", "content": "hi"}],
            ):
                events.append(event)

        token_events = [e for e in events if e["type"] == "token"]
        assert len(token_events) == 2
        assert token_events[0]["content"] == "你好"
        assert token_events[1]["content"] == "世界"

    @pytest.mark.asyncio
    async def test_yields_reasoning_events(self):
        """thinking 开启时流式推送 reasoning 事件。"""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockMessage(reasoning_content="思考中"))]),
            MockChunk(choices=[MockChoice(delta=MockMessage(reasoning_content="..."))]),
            MockChunk(choices=[MockChoice(delta=MockMessage(content="答案"))]),
            MockChunk(choices=[], usage=MockUsage(prompt_tokens=5, completion_tokens=3)),
        ]
        client = _make_stream_client_mock(chunks)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            events = []
            async for event in llm_generate_with_tools_stream(
                messages=[{"role": "user", "content": "hi"}],
                thinking_enabled=True,
            ):
                events.append(event)

        reasoning_events = [e for e in events if e["type"] == "reasoning"]
        assert len(reasoning_events) == 2
        assert reasoning_events[0]["content"] == "思考中"
        assert reasoning_events[1]["content"] == "..."

    @pytest.mark.asyncio
    async def test_yields_tool_call_deltas(self):
        """流式推送 tool_call delta 事件。"""
        # 模拟 tool_call 分多个 chunk 到达
        chunks = [
            # 第一个 chunk: tool_call 开始（id + name）
            MockChunk(
                choices=[
                    MockChoice(
                        delta=MockMessage(
                            tool_calls=[
                                MagicMock(
                                    index=0,
                                    id="call_abc",
                                    function=_make_func_mock(name="search_resume", arguments=""),
                                )
                            ]
                        )
                    )
                ]
            ),
            # 第二个 chunk: arguments 部分拼接
            MockChunk(
                choices=[
                    MockChoice(
                        delta=MockMessage(
                            tool_calls=[
                                MagicMock(
                                    index=0,
                                    id=None,
                                    function=_make_func_mock(name=None, arguments='{"query":'),
                                )
                            ]
                        )
                    )
                ]
            ),
            # 第三个 chunk: arguments 剩余
            MockChunk(
                choices=[
                    MockChoice(
                        delta=MockMessage(
                            tool_calls=[
                                MagicMock(
                                    index=0,
                                    id=None,
                                    function=_make_func_mock(name=None, arguments=' "教育"}'),
                                )
                            ]
                        )
                    )
                ]
            ),
            # usage chunk
            MockChunk(choices=[], usage=MockUsage(prompt_tokens=10, completion_tokens=5)),
        ]
        client = _make_stream_client_mock(chunks)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            events = []
            async for event in llm_generate_with_tools_stream(
                messages=[{"role": "user", "content": "查教育"}],
                tools=[{"type": "function", "function": {"name": "search_resume"}}],
            ):
                events.append(event)

        tool_call_events = [e for e in events if e["type"] == "tool_call_delta"]
        assert len(tool_call_events) >= 1

        # 最终 done 事件应包含完整 tool_calls
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        done = done_events[0]
        assert len(done["tool_calls"]) == 1
        tc = done["tool_calls"][0]
        assert tc.id == "call_abc"
        assert tc.name == "search_resume"
        assert json.loads(tc.arguments) == {"query": "教育"}

    @pytest.mark.asyncio
    async def test_yields_usage_in_final_chunk(self):
        """usage 在最后一个 chunk 中返回。"""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockMessage(content="hi"))]),
            MockChunk(choices=[], usage=MockUsage(prompt_tokens=10, completion_tokens=5)),
        ]
        client = _make_stream_client_mock(chunks)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            with patch("services.rag.pipeline.record_llm_usage", new_callable=AsyncMock) as mock_record:
                events = []
                async for event in llm_generate_with_tools_stream(
                    messages=[{"role": "user", "content": "hi"}],
                    user_id=99,
                ):
                    events.append(event)

        usage_events = [e for e in events if e["type"] == "usage"]
        assert len(usage_events) == 1
        assert usage_events[0]["prompt_tokens"] == 10
        assert usage_events[0]["completion_tokens"] == 5
        mock_record.assert_awaited_once_with(
            99, 10, 5, model=ANY, scenario="tool_call"
        )

    @pytest.mark.asyncio
    async def test_done_event_contains_aggregated_content(self):
        """done 事件包含完整聚合 content。"""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockMessage(content="Hello"))]),
            MockChunk(choices=[MockChoice(delta=MockMessage(content=" World"))]),
            MockChunk(choices=[], usage=MockUsage(prompt_tokens=5, completion_tokens=5)),
        ]
        client = _make_stream_client_mock(chunks)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            events = []
            async for event in llm_generate_with_tools_stream(
                messages=[{"role": "user", "content": "hi"}],
            ):
                events.append(event)

        done = [e for e in events if e["type"] == "done"][0]
        assert done["content"] == "Hello World"
        assert done["tool_calls"] == []

    @pytest.mark.asyncio
    async def test_stream_thinking_not_supported_degrades(self):
        """流式模式不支持 thinking 时无 reasoning 事件，正常返回 token。"""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockMessage(content="答案"))]),
            MockChunk(choices=[], usage=MockUsage(prompt_tokens=5, completion_tokens=3)),
        ]
        client = _make_stream_client_mock(chunks)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            events = []
            async for event in llm_generate_with_tools_stream(
                messages=[{"role": "user", "content": "hi"}],
                thinking_enabled=True,
            ):
                events.append(event)

        reasoning_events = [e for e in events if e["type"] == "reasoning"]
        assert len(reasoning_events) == 0
        token_events = [e for e in events if e["type"] == "token"]
        assert len(token_events) == 1

    @pytest.mark.asyncio
    async def test_stream_empty_choices_skipped(self):
        """空 choices 的信号 chunk 被跳过。"""
        chunks = [
            MockChunk(choices=[]),  # 空信号
            MockChunk(choices=[MockChoice(delta=MockMessage(content="ok"))]),
            MockChunk(choices=[], usage=MockUsage(prompt_tokens=5, completion_tokens=2)),
        ]
        client = _make_stream_client_mock(chunks)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            events = []
            async for event in llm_generate_with_tools_stream(
                messages=[{"role": "user", "content": "hi"}],
            ):
                events.append(event)

        token_events = [e for e in events if e["type"] == "token"]
        assert len(token_events) == 1
        assert token_events[0]["content"] == "ok"

    @pytest.mark.asyncio
    async def test_stream_thinking_param_sent(self):
        """thinking_enabled=True 时流式请求体含 thinking 参数。"""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockMessage(content="ok"))]),
            MockChunk(choices=[], usage=MockUsage()),
        ]
        client = _make_stream_client_mock(chunks)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            async for _ in llm_generate_with_tools_stream(
                messages=[{"role": "user", "content": "hi"}],
                thinking_enabled=True,
                thinking_effort="medium",
            ):
                pass

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"]["type"] == "enabled"
        assert call_kwargs["reasoning_effort"] == "medium"

    @pytest.mark.asyncio
    async def test_stream_include_usage_always_sent(self):
        """流式请求始终包含 stream_options include_usage。"""
        chunks = [
            MockChunk(choices=[MockChoice(delta=MockMessage(content="ok"))]),
            MockChunk(choices=[], usage=MockUsage(prompt_tokens=5, completion_tokens=2)),
        ]
        client = _make_stream_client_mock(chunks)

        with patch("services.rag.pipeline.get_chat_client", return_value=client):
            async for _ in llm_generate_with_tools_stream(
                messages=[{"role": "user", "content": "hi"}],
            ):
                pass

        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("stream") is True
        assert call_kwargs.get("stream_options") == {"include_usage": True}
