"""阶段7 评估体系验收测试（LLM-as-Judge + 黄金数据集）。

严格 TDD 精神：所有测试都不触网、不调真实 DeepSeek。
- 真实 Judge 调用被抽成 judge_client._call_deepseek，本文件用 monkeypatch 替换它返回假 JSON，
  既验证「解析路径」又避免泄露密钥与网络依赖。
- evaluate_entry / compute_composite / needs_reflexion 均为纯逻辑，用 fake judge 直接验证。

运行（在 backend 目录）：python -m pytest tests/test_evaluation_framework.py -q
"""

import json

import pytest

from rag_tuning import judge_client
from rag_tuning.evaluate_judge import (
    GOLDEN_SET_PATH,
    compute_composite,
    evaluate_entry,
    needs_reflexion,
    validate_golden_set,
)
from rag_tuning.judge_client import JudgeResult, REFLEXION_THRESHOLD, WEIGHTS

# ───────────────────── ① 三维度评分与 composite 加权 ─────────────────────


def test_weights_sum_to_one():
    """权重口径必须规范：三维度权重之和=1。"""
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


@pytest.mark.parametrize(
    "completeness,accuracy,source_credibility,expected",
    [
        # 各 1.0 → 1.0
        (1.0, 1.0, 1.0, 1.0),
        # 各 0.5 → 0.5（0.4*0.5 + 0.4*0.5 + 0.2*0.5 = 0.5）
        (0.5, 0.5, 0.5, 0.5),
        # 完整性/准确性满分、来源可信度 0 → 0.8
        (1.0, 1.0, 0.0, 0.8),
        # 仅来源可信度满分 → 0.2
        (0.0, 0.0, 1.0, 0.2),
        # 典型混合：0.9/0.8/0.7 → 0.4*0.9+0.4*0.8+0.2*0.7=0.82
        (0.9, 0.8, 0.7, 0.82),
    ],
)
def test_compute_composite_weighting(completeness, accuracy, source_credibility, expected):
    """composite 必须严格按 0.4/0.4/0.2 加权。"""
    got = compute_composite(completeness, accuracy, source_credibility)
    assert abs(got - expected) < 1e-9


def test_judge_result_composite_matches_weights():
    """JudgeResult.composite 应与 compute_composite 一致。"""
    r = JudgeResult(0.9, 0.8, 0.7, "ok", "deepseek-chat")
    assert abs(r.composite - 0.82) < 1e-9


async def test_evaluate_entry_uses_judged_scores():
    """evaluate_entry 用注入的 judge 打出的三维度分算 composite 并落库记录。"""
    fake_scores = JudgeResult(0.9, 0.8, 0.7, "理由", "fake-judge")

    async def fake_judge(question, answer, reference, sources):
        return fake_scores

    entry = {
        "id": "edu-01",
        "category": "education",
        "answer_type": "factual",
        "question": "哪毕业？",
        "reference_answer": "浙大",
    }
    rec = await evaluate_entry(entry, "浙江大学", None, judge_fn=fake_judge)
    assert rec["id"] == "edu-01"
    assert rec["category"] == "education"
    assert abs(rec["composite"] - 0.82) < 1e-9
    assert rec["scores"]["completeness"] == 0.9
    # needs_reflexion 由 composite 推导
    assert rec["needs_reflexion"] == (rec["composite"] < REFLEXION_THRESHOLD)


# ───────────────────── ② composite < 0.6 → Reflexion 标记 ─────────────────────


def test_needs_reflexion_boundary():
    """严格小于 0.6 才触发；0.6 本身不触发。"""
    assert needs_reflexion(0.59) is True
    assert needs_reflexion(0.6) is False
    assert needs_reflexion(0.61) is False
    assert needs_reflexion(0.0) is True


async def test_evaluate_entry_flags_reflexion_below_threshold():
    """低分答案（composite<0.6）必须标记 needs_reflexion=True。"""
    # 0.4*0.3 + 0.4*0.3 + 0.2*0.3 = 0.3 < 0.6
    low = JudgeResult(0.3, 0.3, 0.3, "差", "fake")

    async def fake_judge(question, answer, reference, sources):
        return low

    entry = {"id": "x", "category": "work", "question": "q", "reference_answer": "ref"}
    rec = await evaluate_entry(entry, "胡说", None, judge_fn=fake_judge)
    assert rec["composite"] == 0.3
    assert rec["needs_reflexion"] is True


async def test_evaluate_entry_no_reflexion_above_threshold():
    """高分答案（composite>0.6）不触发 Reflexion。"""
    high = JudgeResult(0.9, 0.9, 0.9, "好", "fake")

    async def fake_judge(question, answer, reference, sources):
        return high

    entry = {"id": "y", "category": "skill", "question": "q", "reference_answer": "ref"}
    rec = await evaluate_entry(entry, "准确", None, judge_fn=fake_judge)
    assert rec["needs_reflexion"] is False


# ───────────────────── Judge 客户端解析（不触网，monkeypatch 假返回）─────────────────────


async def test_judge_client_parses_deepseek_json(monkeypatch):
    """monkeypatch _call_deepseek 返回假 JSON，验证真实解析路径能拿到三维度分。"""

    fake_json = json.dumps(
        {
            "completeness": 0.85,
            "accuracy": 0.9,
            "source_credibility": 0.8,
            "rationale": "答案覆盖了关键点且能对应来源",
        }
    )

    async def fake_call(prompt: str) -> str:
        return fake_json

    monkeypatch.setattr(judge_client, "_call_deepseek", fake_call)
    result = await judge_client.judge("问题", "答案", "参考", [{"text": "来源片段"}])
    assert isinstance(result, JudgeResult)
    assert result.completeness == 0.85
    assert result.accuracy == 0.9
    assert result.source_credibility == 0.8
    assert "覆盖" in result.rationale
    # composite 加权：0.4*0.85+0.4*0.9+0.2*0.8 = 0.86
    assert abs(result.composite - 0.86) < 1e-9


async def test_judge_client_handles_code_fence(monkeypatch):
    """DeepSeek 偶尔用 ```json 围栏包裹，解析需鲁棒。"""

    async def fake_call(prompt: str) -> str:
        return (
            '```json\n{"completeness":1,"accuracy":1,"source_credibility":1,"rationale":"x"}\n```'
        )

    monkeypatch.setattr(judge_client, "_call_deepseek", fake_call)
    result = await judge_client.judge("q", "a", "r", None)
    assert result.completeness == 1.0
    assert result.composite == 1.0


# ───────────────────── ③ golden_set.json 可解析/字段齐全/条目数达标/维度覆盖 ─────────────────────

# 旧 golden_set.json 已删除，数据集迁移至 eval_data/golden_set_v2.json，由 v2 框架 (eval/) 取代。
# 以下测试保留作回归保护，但数据集不存在时自动跳过。
_skip_no_golden = pytest.mark.skipif(
    not GOLDEN_SET_PATH.exists(),
    reason="旧 golden_set.json 已迁移至 eval_data/golden_set_v2.json，由 v2 框架 (eval/) 取代",
)


@_skip_no_golden
def test_golden_set_file_exists_and_is_json():
    assert GOLDEN_SET_PATH.exists(), f"缺少 {GOLDEN_SET_PATH}"
    data = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "resumes" in data and "qa" in data


@_skip_no_golden
def test_validate_golden_set_passes():
    """校验函数应通过现有数据集，并返回解析结果。"""
    data = validate_golden_set(GOLDEN_SET_PATH)
    assert len(data["qa"]) >= 10
    assert len(data["resumes"]) >= 1


@_skip_no_golden
def test_golden_set_entry_fields_complete():
    """每条 qa 必含 id/resume_id/category/question/reference_answer，且 resume_id 存在。"""
    data = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    resume_ids = {str(k) for k in data["resumes"].keys()}
    for e in data["qa"]:
        for f in ("id", "resume_id", "category", "question", "reference_answer"):
            assert f in e, f"条目 {e.get('id')} 缺少字段 {f}"
        assert str(e["resume_id"]) in resume_ids, f"resume_id 未匹配：{e['resume_id']}"


@_skip_no_golden
def test_golden_set_covers_multiple_dimensions():
    """维度覆盖需 ≥ 4（避免评测偏科）。"""
    data = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    categories = {e.get("category") for e in data["qa"]}
    assert len(categories) >= 4, f"维度覆盖不足：{categories}"


@_skip_no_golden
def test_golden_set_entry_count_meets_minimum():
    """条目数需 ≥ 10（计划要求）。"""
    data = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    assert len(data["qa"]) >= 10


# 顺带确认：graph 的导入只在函数体内（缩进），不在模块顶层（避免与阶段11 并发重构 import 挂）
def test_evaluate_module_does_not_import_graph_at_top_level():
    import inspect

    import rag_tuning.evaluate_judge as mod

    src = inspect.getsource(mod)
    # 只匹配真正的 import 语句行（排除 docstring 里的同名文字说明）
    import_lines = [
        ln
        for ln in src.splitlines()
        if ln.strip().startswith("from services.agentic_rag.graph import")
    ]
    assert import_lines, "graph 导入应存在于 _run_graph 函数体内"
    # 所有出现都必须带缩进（在函数内），不允许出现在模块顶层（列0）
    assert all(
        ln.startswith((" ", "\t")) for ln in import_lines
    ), "graph 导入必须在函数体内缩进，不能在模块顶层"
