"""T8 provider profile contract tests."""

from core.config import settings
from services.rag.pipeline import _build_llm_kwargs
from services.rag.provider_profiles import list_provider_profiles
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def test_profile_matrix_covers_required_scenarios():
    profiles = list_provider_profiles()
    assert {
        "resume_extract",
        "qa_simple",
        "qa_complex",
        "field_rewrite",
        "resume_compare",
        "tool_call",
        "judge",
    } <= profiles.keys()
    assert profiles["field_rewrite"].thinking is False
    assert profiles["qa_complex"].thinking is True
    assert profiles["tool_call"].use_tools is True


def test_deepseek_thinking_request_uses_extra_body_and_effort():
    body = _build_llm_kwargs(
        model_name="deepseek-v4-flash",
        messages=[{"role": "user", "content": "x"}],
        temperature=0.1,
        max_tokens=None,
        tools=None,
        thinking_enabled=None,
        thinking_effort=None,
        scenario="qa_complex",
    )
    assert body["extra_body"] == {"thinking": {"type": "enabled"}}
    assert body["reasoning_effort"] == "high"


def test_structured_profile_explicitly_disables_thinking():
    body = _build_llm_kwargs(
        model_name="deepseek-v4-flash",
        messages=[],
        temperature=0.1,
        max_tokens=None,
        tools=None,
        thinking_enabled=None,
        thinking_effort=None,
        scenario="field_rewrite",
    )
    assert body["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in body


def test_judge_does_not_receive_deepseek_only_fields():
    body = _build_llm_kwargs(
        model_name=settings.JUDGE_MODEL,
        messages=[],
        temperature=0.0,
        max_tokens=None,
        tools=None,
        thinking_enabled=True,
        thinking_effort="high",
        scenario="judge",
    )
    assert "extra_body" not in body
    assert "reasoning_effort" not in body


@pytest.mark.asyncio
async def test_llm_generate_preserves_complex_thinking_profile():
    from services.rag import pipeline

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="ok"))]
    response.usage = None
    client.chat.completions.create = AsyncMock(return_value=response)

    with patch.object(pipeline, "get_chat_client", return_value=client):
        result = await pipeline.llm_generate(
            "system", "user", scenario="qa_complex", model="deepseek-v4-flash"
        )

    assert result == "ok"
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert kwargs["reasoning_effort"] == "high"
