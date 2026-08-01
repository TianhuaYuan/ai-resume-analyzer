"""T36：Agent / Builder / 反解析 指标验收测试。

验证 core/metrics.py 新增的 6 个指标 + LLM call_site 标签扩展：
- rag_agent_loop_total / rag_agent_tool_calls_total / rag_agent_tool_duration_seconds
- rag_agent_tokens_total / resume_builder_total / resume_parse_total
- LLM 四指标新增 call_site 标签（默认 "unknown"）

REGISTRY 是跨测试共享的模块级单例，故一律采用「前后差值」断言，
避免受其他测试遗留状态影响。
"""

from core.metrics import (
    REGISTRY,
    record_agent_loop,
    record_agent_tool_call,
    record_agent_tokens,
    record_resume_builder,
    record_resume_parse,
    record_token_usage,
)


def _val(name: str, labels: dict) -> float:
    """读取指标样本值，样本不存在时返回 0.0。"""
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ── T36-1：Agent 循环计数（success / timeout / error）──────────────────────────
def test_agent_loop_metrics():
    before = _val("rag_agent_loop_total", {"status": "success"})
    record_agent_loop("success")
    after = _val("rag_agent_loop_total", {"status": "success"})
    assert after == before + 1

    # timeout / error 两个状态维度同样可独立计数
    t_before = _val("rag_agent_loop_total", {"status": "timeout"})
    e_before = _val("rag_agent_loop_total", {"status": "error"})
    record_agent_loop("timeout")
    record_agent_loop("error")
    assert _val("rag_agent_loop_total", {"status": "timeout"}) == t_before + 1
    assert _val("rag_agent_loop_total", {"status": "error"}) == e_before + 1


# ── T36-2/3：Agent 工具调用计数 + 耗时直方图 ────────────────────────────────────
def test_agent_tool_metrics():
    tool = "vector_search"
    c_before = _val("rag_agent_tool_calls_total", {"tool_name": tool, "status": "success"})
    cnt_before = _val("rag_agent_tool_duration_seconds_count", {"tool_name": tool})

    record_agent_tool_call(tool, "success", 0.05)

    assert (
        _val("rag_agent_tool_calls_total", {"tool_name": tool, "status": "success"})
        == c_before + 1
    )
    # 直方图观测数 +1
    assert (
        _val("rag_agent_tool_duration_seconds_count", {"tool_name": tool})
        == cnt_before + 1
    )
    # 直方图累加和应不少于本次观测值
    assert _val("rag_agent_tool_duration_seconds_sum", {"tool_name": tool}) >= 0.05

    # error 状态独立计数，不混入 success
    err_before = _val("rag_agent_tool_calls_total", {"tool_name": tool, "status": "error"})
    record_agent_tool_call(tool, "error", 0.01)
    assert (
        _val("rag_agent_tool_calls_total", {"tool_name": tool, "status": "error"})
        == err_before + 1
    )


# ── T36-4：Agent token 消耗（prompt / completion 分计）─────────────────────────
def test_agent_token_metrics():
    p_before = _val("rag_agent_tokens_total", {"type": "prompt"})
    c_before = _val("rag_agent_tokens_total", {"type": "completion"})

    record_agent_tokens(prompt_tokens=100, completion_tokens=50)

    assert _val("rag_agent_tokens_total", {"type": "prompt"}) == p_before + 100
    assert _val("rag_agent_tokens_total", {"type": "completion"}) == c_before + 50

    # 0 值不产生样本：再次调用后 prompt 仍只 +100
    record_agent_tokens(prompt_tokens=0, completion_tokens=0)
    assert _val("rag_agent_tokens_total", {"type": "prompt"}) == p_before + 100


# ── T36-5：简历构建（create / draft / complete）────────────────────────────────
def test_resume_builder_metrics():
    for action in ("create", "draft", "complete"):
        before = _val("resume_builder_total", {"action": action})
        record_resume_builder(action)
        assert _val("resume_builder_total", {"action": action}) == before + 1


# ── T36-6：简历反解析（success / error）─────────────────────────────────────────
def test_resume_parse_metrics():
    s_before = _val("resume_parse_total", {"status": "success"})
    e_before = _val("resume_parse_total", {"status": "error"})

    record_resume_parse("success")
    record_resume_parse("error")

    assert _val("resume_parse_total", {"status": "success"}) == s_before + 1
    assert _val("resume_parse_total", {"status": "error"}) == e_before + 1


# ── T36-7：LLM call_site 标签扩展 ───────────────────────────────────────────────
def test_llm_call_site_label():
    labels = {"model": "gpt-4o", "type": "prompt", "call_site": "test_site"}
    before = _val("app_llm_tokens_total", labels)

    record_token_usage(
        model="gpt-4o",
        prompt_tokens=42,
        completion_tokens=0,
        call_site="test_site",
    )

    assert _val("app_llm_tokens_total", labels) == before + 42

    # 未传 call_site 时落默认 "unknown"，向后兼容既有调用方
    record_token_usage(model="gpt-4o", prompt_tokens=1, completion_tokens=0)
    assert (
        _val(
            "app_llm_tokens_total",
            {"model": "gpt-4o", "type": "prompt", "call_site": "unknown"},
        )
        >= 1
    )
