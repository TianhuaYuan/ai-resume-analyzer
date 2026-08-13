from services.ai_contracts import AIRequest, AIStreamEvent, UsageRecord


def test_ai_request_is_provider_neutral():
    request = AIRequest(
        scenario="qa_complex",
        messages=[{"role": "user", "content": "hello"}],
        thinking_enabled=True,
        thinking_effort="high",
    )

    assert request.scenario == "qa_complex"
    assert request.thinking_enabled is True
    assert request.messages[0]["role"] == "user"


def test_usage_record_normalizes_missing_and_negative_values():
    usage = UsageRecord.from_usage(
        {"prompt_tokens": -1, "completion_tokens": 3},
        model="test-model",
        scenario="qa_simple",
        user_id=7,
    )

    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 3
    assert usage.total_tokens == 3
    assert usage.as_dict()["scenario"] == "qa_simple"


def test_stream_event_contains_recovery_metadata():
    event = AIStreamEvent(
        event_type="tool_result",
        sequence=4,
        turn_id="turn-1",
        tool_call_id="tool-1",
        payload={"tool_name": "search_resume"},
    ).as_dict()

    assert event["protocol_version"] == "1"
    assert event["sequence"] == 4
    assert event["turn_id"] == "turn-1"
    assert event["tool_call_id"] == "tool-1"
