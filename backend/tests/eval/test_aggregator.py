"""test_aggregator — 空输入安全、全满分、精确手算、延迟阶梯、delta、ranking。"""

from __future__ import annotations

from eval.aggregator import (
    aggregate,
    by_asker,
    by_category,
    by_difficulty,
    delta_from_baseline,
    experiment_composite,
    ranking,
)
from eval.protocol import EvalEntry, ExecutorResult, JudgeResult


def _mk(
    faith, comp, hall, rej,
    *,
    refused=False, should=None, latency=0.0,
    category="factual", difficulty="easy", asker="hr",
):
    answer = "抱歉 未提及" if refused else "正常答案"
    sources = [] if refused else [{"text": "ctx", "section": ""}]
    jr = JudgeResult(
        faithfulness=faith, completeness=comp, hallucination_score=hall,
        reject_correctness=rej, rationale="r", model="m",
    )
    params = {}
    if should is not None:
        params["_should_answer"] = should
    return EvalEntry(
        sample_id="s", category=category, difficulty=difficulty, asker=asker,
        question="q", answer=answer, reference_answer="ref",
        params=params, executor_result=ExecutorResult(answer=answer, sources=sources),
        judge_result=jr, composite=jr.composite, needs_reflexion=jr.needs_reflexion,
        latency_ms=latency,
    )


def test_empty_is_safe():
    agg = aggregate([])
    assert agg == {k: 0.0 for k in agg}
    assert experiment_composite(agg) == 0.0


def test_all_perfect():
    results = [_mk(1.0, 1.0, 0.0, 1.0) for _ in range(3)]
    agg = aggregate(results)
    assert agg["avg_composite"] == 1.0
    assert agg["min_composite"] == 1.0
    assert agg["composite_stddev"] == 0.0
    assert agg["avg_faithfulness"] == 1.0
    assert agg["avg_completeness"] == 1.0
    assert agg["avg_reject_correctness"] == 1.0
    assert agg["hallucination_rate"] == 0.0  # hall=0 不 > 0.5
    assert agg["p95_latency"] == 0.0


def test_exact_aggregate():
    # 2 条，维度明确
    r1 = _mk(1.0, 0.0, 0.0, 1.0, latency=100.0)
    r2 = _mk(0.0, 1.0, 1.0, 0.0, latency=300.0)
    agg = aggregate([r1, r2])
    assert abs(agg["avg_faithfulness"] - 0.5) < 1e-9
    assert abs(agg["avg_completeness"] - 0.5) < 1e-9
    assert abs(agg["avg_composite"] - 0.5) < 1e-9
    assert agg["hallucination_rate"] == 0.5  # 仅 r2 hall>0.5
    # 2 个点 [100,300]，线性插值 p95 = 100 + 0.95*(300-100) = 290
    assert abs(agg["p95_latency"] - 290.0) < 1e-9


def test_reject_metrics_exact():
    # TP / FN / FP / TN 各一
    tp = _mk(1.0, 1.0, 0.0, 1.0, refused=True, should=False)
    fn = _mk(1.0, 1.0, 0.0, 1.0, refused=False, should=False)
    fp = _mk(1.0, 1.0, 0.0, 1.0, refused=True, should=True)
    tn = _mk(1.0, 1.0, 0.0, 1.0, refused=False, should=True)
    agg = aggregate([tp, fn, fp, tn])
    assert abs(agg["reject_precision"] - 0.5) < 1e-9
    assert abs(agg["reject_recall"] - 0.5) < 1e-9
    assert abs(agg["reject_f1"] - 0.5) < 1e-9


def test_p95_latency_percentile():
    latencies = [i * 100.0 for i in range(11)]  # 0..1000
    results = [_mk(1.0, 1.0, 0.0, 1.0, latency=lat) for lat in latencies]
    agg = aggregate(results)
    # 0.95*(11-1)=9.5 → 线性插值 900..1000 → 950
    assert abs(agg["p95_latency"] - 950.0) < 1e-6


def test_experiment_composite_latency_tiers():
    base = {"avg_faithfulness": 1.0, "avg_completeness": 1.0}
    assert experiment_composite({**base, "p95_latency": 2000.0}) == 1.0
    assert experiment_composite({**base, "p95_latency": 4000.0}) == 0.95
    assert experiment_composite({**base, "p95_latency": 8000.0}) == 0.85
    assert experiment_composite({**base, "p95_latency": 12000.0}) == 0.70
    # base=0.5, p95=2000 → 0.5
    assert experiment_composite({"avg_faithfulness": 0.5, "avg_completeness": 0.5, "p95_latency": 2000.0}) == 0.5


def test_delta_sign():
    cur = {"avg_composite": 0.8, "avg_faithfulness": 0.9}
    base = {"avg_composite": 0.5, "avg_faithfulness": 0.6}
    d = delta_from_baseline(cur, base)
    assert abs(d["avg_composite"] - 0.3) < 1e-9
    assert abs(d["avg_faithfulness"] - 0.3) < 1e-9
    # 反向（下降）
    d2 = delta_from_baseline(base, cur)
    assert abs(d2["avg_composite"] - (-0.3)) < 1e-9


def test_ranking_order():
    a = {"avg_faithfulness": 1.0, "avg_completeness": 1.0, "p95_latency": 1000.0}
    b = {"avg_faithfulness": 0.5, "avg_completeness": 0.5, "p95_latency": 1000.0}
    r = ranking([("B", b), ("A", a)])
    assert r[0]["label"] == "A"  # ec=1.0 > 0.5
    assert r[1]["label"] == "B"
    assert r[0]["experiment_composite"] == 1.0
    assert r[0]["composite"] == 1.0


def test_groupings():
    r1 = _mk(1.0, 1.0, 0.0, 1.0, category="factual", difficulty="easy", asker="hr")
    r2 = _mk(0.0, 0.0, 1.0, 0.0, category="reasoning", difficulty="hard", asker="tech_interviewer")
    cat = by_category([r1, r2])
    assert set(cat.keys()) == {"factual", "reasoning"}
    assert cat["factual"]["avg_faithfulness"] == 1.0
    diff = by_difficulty([r1, r2])
    assert set(diff.keys()) == {"easy", "hard"}
    ask = by_asker([r1, r2])
    assert set(ask.keys()) == {"hr", "tech_interviewer"}
