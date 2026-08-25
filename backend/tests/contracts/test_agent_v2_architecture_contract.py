"""Phase 0 architecture contract guard.

This suite intentionally imports no production module. Later phases should add
behavioral contract tests beside it while keeping these vocabulary guards.
"""

import re
from pathlib import Path


CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "architecture"
    / "agent-v2.md"
)


def _contract_text() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def _section(text: str, heading: str, next_heading: str | None = None) -> str:
    start = text.index(heading)
    end = text.index(next_heading, start) if next_heading else len(text)
    return text[start:end]


def _table_first_column(section: str, header: str) -> list[str]:
    """Return data-row names from one Markdown table, excluding header/separator."""
    lines = section.splitlines()
    header_index = next(
        index for index, line in enumerate(lines) if line.startswith(f"| {header} |")
    )
    values: list[str] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        values.append(line.split("|", 2)[1].strip())
    return values


def test_required_architecture_sections_are_present():
    text = _contract_text()
    required = (
        "## 1. 当前调用图",
        "## 2. 目标六层架构",
        "## 3. 路由矩阵",
        "## 4. 核心不变量",
        "## 5. 统一概念",
        "## 6. Phase 1-7 迁移顺序",
        "## 7. 明确非目标",
    )
    assert all(section in text for section in required)


def test_six_layers_and_four_routes_are_closed_sets():
    text = _contract_text()
    layers = _section(text, "## 2. 目标六层架构", "## 3. 路由矩阵")
    routes = _section(text, "## 3. 路由矩阵", "## 4. 核心不变量")
    assert _table_first_column(layers, "层") == ["L1", "L2", "L3", "L4", "L5", "L6"]
    assert _table_first_column(routes, "Route") == [
        "Direct Service",
        "Direct RAG",
        "Agentic RAG",
        "ReAct",
    ]


def test_each_layer_has_responsibility_and_prohibition():
    text = _section(_contract_text(), "## 2. 目标六层架构", "## 3. 路由矩阵")
    expected = {
        "L1": ("FastAPI DTO", "选择工具"),
        "L2": ("创建 `Run`", "直接访问 Chroma"),
        "L3": ("执行 Direct Service", "持有数据库模型"),
        "L4": ("工具注册", "决定全局路由"),
        "L5": ("Artifact 聚合", "调用具体 LLM provider"),
        "L6": ("DB/vector/LLM/provider adapter", "产品意图"),
    }
    for layer, (responsibility, forbidden) in expected.items():
        row = next(line for line in text.splitlines() if line.startswith(f"| {layer} |"))
        assert responsibility in row
        assert forbidden in row


def test_route_matrix_freezes_control_and_write_semantics():
    text = _section(_contract_text(), "## 3. 路由矩阵", "## 4. 核心不变量")
    expected_fragments = {
        "Direct Service": ("规则确定", "否 | 否 | 否", "service 自身事务"),
        "Direct RAG": ("一次检索足够", "一次受限检索", "只读"),
        "Agentic RAG": ("多轮补检", "仅检索域", "只读"),
        "ReAct": ("步骤未知", "白名单工具", "只产出 `Proposal`"),
    }
    for route, fragments in expected_fragments.items():
        row = next(line for line in text.splitlines() if line.startswith(f"| {route} |"))
        assert all(fragment in row for fragment in fragments)
    assert "不得静默升级" in text
    assert "能用 Direct Service 不用 LLM" in text


def test_all_twelve_invariants_have_required_meaning():
    text = _section(_contract_text(), "## 4. 核心不变量", "## 5. 统一概念")
    invariants = {
        int(number): body
        for number, body in re.findall(r"^(\d+)\. \*\*(.+)$", text, re.MULTILINE)
    }
    assert set(invariants) == set(range(1, 13))
    keywords = {
        1: ("Artifact", "事实源", "版本"),
        2: ("证据", "Evidence", "provenance"),
        3: ("user_id", "scope", "隔离"),
        4: ("一个 Run", "run_id", "turn_id"),
        5: ("sequence", "terminal", "递增"),
        6: ("closed-world", "ToolResult", "异常"),
        7: ("Proposal", "apply", "读写分离"),
        8: ("降级", "Run.degraded", "最终响应"),
        9: ("预算", "token", "父预算"),
        10: ("取消", "审计", "副作用"),
        11: ("provider", "adapter", "解耦"),
        12: ("兼容", "adapter", "重写"),
    }
    for number, required in keywords.items():
        assert all(word in invariants[number] for word in required)


def test_unified_concepts_remain_explicit():
    text = _contract_text()
    for concept in ("Evidence", "Run", "Event", "ToolResult", "Proposal"):
        assert f"### {concept}" in text


def test_unified_concept_required_fields_and_states():
    text = _section(_contract_text(), "## 5. 统一概念", "## 6. Phase 1-7 迁移顺序")
    required_fields = {
        "Evidence": ("evidence_id", "source_kind", "asset_id", "asset_version", "locator", "excerpt", "provenance"),
        "Run": ("run_id", "turn_id", "user_id", "route", "status", "scope", "budget", "started_at"),
        "Event": ("protocol_version", "event_id", "event_type", "run_id", "turn_id", "sequence", "occurred_at", "payload"),
        "ToolResult": ("call_id", "tool_name", "status", "output", "evidence", "error", "usage", "started_at", "finished_at"),
        "Proposal": ("proposal_id", "run_id", "target_asset_id", "base_version", "operations", "rationale", "evidence", "risk", "status"),
    }
    headings = list(required_fields)
    for index, concept in enumerate(headings):
        start = text.index(f"### {concept}")
        end = text.index(f"### {headings[index + 1]}", start) if index + 1 < len(headings) else len(text)
        block = text[start:end]
        assert all(f"`{field}`" in block for field in required_fields[concept])
    assert "awaiting_approval` 是非终态" in text
    assert "awaiting_approval -> running" in text
    assert "`succeeded | failed | cancelled` 是且仅是 terminal" in text
    assert all(
        fragment in text
        for fragment in ("`finished_at`", "`degraded`", "`usage`", "terminal outcome")
    )
    assert "succeeded | failed | rejected | cancelled" in text
    assert "成功不得携带 error" in text
    assert "失败不得用自然语言 success output 掩盖" in text
    assert "draft | awaiting_approval | approved | rejected | applied | stale" in text
    assert all(
        fragment in text
        for fragment in ("校验 `base_version`", "权限", "审批", "幂等键", "版本冲突转 `stale`")
    )


def test_event_core_family_is_complete():
    text = _section(_contract_text(), "### Event", "### ToolResult")
    event_types = (
        "run_started",
        "route_selected",
        "retrieval_started",
        "evidence_added",
        "tool_started",
        "tool_finished",
        "proposal_created",
        "approval_required",
        "answer_delta",
        "run_completed",
        "run_failed",
        "run_cancelled",
    )
    assert all(f"`{event_type}`" in text for event_type in event_types)


def test_migration_phases_are_complete_and_ordered():
    text = _section(_contract_text(), "## 6. Phase 1-7 迁移顺序", "## 7. 明确非目标")
    phases = [int(value) for value in re.findall(r"^\d+\. \*\*Phase (\d+) —", text, re.MULTILINE)]
    assert phases == list(range(1, 8))
    required = {
        1: "Contract types",
        2: "Evidence normalization",
        3: "Run and Event backbone",
        4: "Capability ports",
        5: "Router convergence",
        6: "Proposal write path",
        7: "Cutover and cleanup",
    }
    for phase, name in required.items():
        assert f"**Phase {phase} — {name}**" in text


def test_non_goals_are_explicit_and_git_reproduction_is_documented():
    text = _section(_contract_text(), "## 7. 明确非目标", "## 8. Phase 0 验收")
    for fragment in (
        "不修改任何生产逻辑",
        "不在本轮重写 LangGraph",
        "不承诺 autonomous job application",
        "不把 memory 当事实源",
        "Direct Service 是长期保留",
        "不绑定单一 LLM",
        "不在架构迁移中顺带改变简历评分规则",
    ):
        assert fragment in text
    acceptance = _section(_contract_text(), "## 8. Phase 0 验收")
    assert "`.gitignore` 忽略 `docs/`" in acceptance
    assert "git add -f docs/architecture/agent-v2.md" in acceptance


def test_current_call_graph_distinguishes_json_and_sse_paths():
    text = _section(_contract_text(), "## 1. 当前调用图", "## 2. 目标六层架构")
    for fragment in (
        "ASK -->|only| AR_JSON[agentic_rag.runner for JSON]",
        "AR_JSON --> JSON[AnswerResponse JSON]",
        "STREAM -->|mode=agentic only| AR_STREAM[agentic_rag.runner for stream]",
        "AR_STREAM --> SSEA[/ask/stream agentic SSE: status/token/done]",
        "hybrid_search_corpus",
        "Chroma + BM25",
        "|direct_answer|",
        "DIRECT --> OUTPUT[output]",
    ):
        assert fragment in text


def test_phase_zero_forbids_production_logic_changes():
    assert "Phase 0 不修改任何生产逻辑" in _contract_text()
