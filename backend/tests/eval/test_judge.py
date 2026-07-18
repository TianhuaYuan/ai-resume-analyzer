"""test_judge — FakeScorer 形状 + DeepSeekScorer 3D→4D 适配与 reject_correctness 逻辑 + n_runs median。"""

from __future__ import annotations

import pytest

import rag_tuning.judge_client as jc
from eval.judge import (
    DeepSeekScorer,
    FakeScorer,
    Scorer,
    compute_reject_correctness,
)
from eval.protocol import JudgeResult


def _fake_old_judge(completeness, accuracy, source_credibility, rationale="r", model="deepseek-v4-flash"):
    return jc.JudgeResult(
        completeness=completeness,
        accuracy=accuracy,
        source_credibility=source_credibility,
        rationale=rationale,
        model=model,
    )


async def test_fake_scorer_shape():
    s = FakeScorer()
    jr = await s.judge("q", "a", "ref", sources=[{"text": "x"}])
    assert isinstance(jr, JudgeResult)
    assert (jr.faithfulness, jr.completeness, jr.hallucination_score, jr.reject_correctness) == (1.0, 1.0, 0.0, 1.0)
    assert jr.model == "fake"


def test_scorer_is_abstract():
    # Scorer 不能直接实例化（抽象方法未实现）
    with pytest.raises(TypeError):
        Scorer()


async def test_deepseek_adapter_mapping(monkeypatch):
    # n_runs=1 直通：测试 3D→4D 维度适配
    async def _fake_judge(question, answer, reference, sources=None):
        return _fake_old_judge(
            completeness=0.8, accuracy=0.6, source_credibility=0.4,
            rationale="ok", model="deepseek-v4-flash",
        )

    monkeypatch.setattr(jc, "judge", _fake_judge)

    scorer = DeepSeekScorer(n_runs=1)
    jr = await scorer.judge(
        "q", "answer text", "ref",
        sources=[{"text": "ctx"}],
        should_answer=True,
    )
    # 维度适配：faithfulness←accuracy(0.6), completeness←completeness(0.8)
    assert jr.faithfulness == 0.6
    assert jr.completeness == 0.8
    # hallucination_score = 1 - source_credibility = 0.6
    assert jr.hallucination_score == 0.6
    assert jr.rationale == "ok"
    assert jr.model == "deepseek-v4-flash"


async def test_reject_correctness_logic(monkeypatch):
    async def _fake_judge(question, answer, reference, sources=None):
        return _fake_old_judge(1.0, 1.0, 1.0)

    monkeypatch.setattr(jc, "judge", _fake_judge)
    scorer = DeepSeekScorer(n_runs=1)

    # should_answer=None → 1.0（未知）
    jr = await scorer.judge("q", "a", "ref", sources=[{"text": "x"}], should_answer=None)
    assert jr.reject_correctness == 1.0

    # 该答 & 答了 → 1.0
    jr = await scorer.judge("q", "正常答案", "ref", sources=[{"text": "x"}], should_answer=True)
    assert jr.reject_correctness == 1.0

    # 该答 & 拒了（无来源）→ 0.0
    jr = await scorer.judge("q", "正常答案", "ref", sources=[], should_answer=True)
    assert jr.reject_correctness == 0.0

    # 该答 & 拒了（以"抱歉"开头）→ 0.0
    jr = await scorer.judge("q", "抱歉没找到", "ref", sources=[{"text": "x"}], should_answer=True)
    assert jr.reject_correctness == 0.0

    # 不该答 & 拒了（无来源）→ 1.0
    jr = await scorer.judge("q", "x", "ref", sources=[], should_answer=False)
    assert jr.reject_correctness == 1.0

    # 不该答 & 答了 → 0.0
    jr = await scorer.judge("q", "正常答案", "ref", sources=[{"text": "x"}], should_answer=False)
    assert jr.reject_correctness == 0.0


async def test_deepseek_error_fallback(monkeypatch):
    async def _boom(question, answer, reference, sources=None):
        raise RuntimeError("API down")

    monkeypatch.setattr(jc, "judge", _boom)
    scorer = DeepSeekScorer(n_runs=1)
    jr = await scorer.judge("q", "a", "ref", sources=[{"text": "x"}], should_answer=True)
    # 降级：各维度 0.5，rationale 含 error
    assert jr.faithfulness == 0.5
    assert jr.completeness == 0.5
    assert "error" in jr.rationale
    # 但 reject_correctness 仍按 should_answer 计算
    assert jr.reject_correctness == 1.0


def test_compute_reject_correctness_unit():
    assert compute_reject_correctness("a", [{"text": "x"}], None) == 1.0
    assert compute_reject_correctness("a", [{"text": "x"}], True) == 1.0
    assert compute_reject_correctness("抱歉", [], True) == 0.0
    assert compute_reject_correctness("a", [{"text": "x"}], False) == 0.0
    assert compute_reject_correctness("抱歉", [], False) == 1.0


async def test_n_runs_median(monkeypatch):
    """n_runs=3 时并发调用 3 次，各维度取中位数。"""
    call_count = 0

    async def _variable_judge(question, answer, reference, sources=None):
        nonlocal call_count
        call_count += 1
        # 三次返回不同值，中位数应为第二次
        values = [
            (0.9, 0.7, 0.8),  # run 1
            (0.5, 0.5, 0.5),  # run 2 (median)
            (0.1, 0.3, 0.2),  # run 3
        ]
        c, a, sc = values[(call_count - 1) % 3]
        return _fake_old_judge(completeness=c, accuracy=a, source_credibility=sc)

    monkeypatch.setattr(jc, "judge", _variable_judge)
    scorer = DeepSeekScorer(n_runs=3)
    jr = await scorer.judge("q", "a", "ref", sources=[{"text": "x"}], should_answer=True)

    assert call_count == 3
    # median of [0.9, 0.5, 0.1] = 0.5 (faithfulness ← accuracy)
    assert jr.faithfulness == 0.5
    # median of [0.7, 0.5, 0.3] = 0.5 (completeness)
    assert jr.completeness == 0.5
    # median of [0.2, 0.5, 0.8] = 0.5 (hallucination ← 1 - source_credibility)
    assert jr.hallucination_score == 0.5
    assert "median of 3/3" in jr.rationale


async def test_n_runs_partial_failure(monkeypatch):
    """n_runs=3 时部分调用失败，用成功的取中位数。"""
    call_count = 0

    async def _flaky_judge(question, answer, reference, sources=None):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("transient error")
        return _fake_old_judge(completeness=0.8, accuracy=0.6, source_credibility=0.4)

    monkeypatch.setattr(jc, "judge", _flaky_judge)
    scorer = DeepSeekScorer(n_runs=3)
    jr = await scorer.judge("q", "a", "ref", sources=[{"text": "x"}], should_answer=True)

    assert call_count == 3
    # 2/3 成功，值相同，median = 0.6
    assert jr.faithfulness == 0.6
    assert "median of 2/3" in jr.rationale


async def test_n_runs_all_fail(monkeypatch):
    """n_runs=3 时全部失败 → 降级 0.5。"""
    async def _boom(question, answer, reference, sources=None):
        raise RuntimeError("total outage")

    monkeypatch.setattr(jc, "judge", _boom)
    scorer = DeepSeekScorer(n_runs=3)
    jr = await scorer.judge("q", "a", "ref", sources=[{"text": "x"}], should_answer=True)

    assert jr.faithfulness == 0.5
    assert jr.completeness == 0.5
    assert "all 3 runs failed" in jr.rationale
    # reject_correctness 仍正常计算
    assert jr.reject_correctness == 1.0
