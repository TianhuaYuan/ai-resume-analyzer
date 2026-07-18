"""test_reporter — HTML 报告生成与对比。"""

from __future__ import annotations


from eval.protocol import EvalEntry, EvalReport, ExecutorResult, JudgeResult
from eval.reporter import Reporter


def _mk_entry(sid: str, faith: float, comp: float, latency: float = 100.0):
    jr = JudgeResult(faithfulness=faith, completeness=comp, hallucination_score=0.0,
                     reject_correctness=1.0, rationale="r", model="m")
    return EvalEntry(
        sample_id=sid, category="factual", difficulty="easy", asker="hr",
        question=f"Q{sid}", answer=f"A{sid}", reference_answer="ref",
        params={}, executor_result=ExecutorResult(answer=f"A{sid}", sources=[{"text": "x"}]),
        judge_result=jr, composite=jr.composite, needs_reflexion=jr.needs_reflexion,
        latency_ms=latency,
    )


def _mk_report(label: str, faith: float) -> EvalReport:
    entries = [_mk_entry("1", faith, 0.8), _mk_entry("2", faith, 0.6, latency=200.0)]
    from eval.aggregator import aggregate, by_category, experiment_composite
    summary = aggregate(entries)
    summary["experiment_composite"] = experiment_composite(summary)
    return EvalReport(
        summary=summary,
        per_sample=entries,
        per_category=by_category(entries),
        ranking=[{"label": label, "experiment_composite": summary["experiment_composite"],
                  "composite": summary["experiment_composite"], **summary}],
    )


def test_render_html(tmp_path):
    rep = _mk_report("config_A", 0.9)
    out = Reporter().render(rep, tmp_path / "report.html")
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "RAG 评估报告" in html
    assert "参数组排名" in html
    assert "config_A" in html
    assert "逐条样本" in html


def test_render_comparison(tmp_path):
    rep_a = _mk_report("config_A", 0.9)
    rep_b = _mk_report("config_B", 0.6)
    out = Reporter().render_comparison([rep_a, rep_b], ["实验A", "实验B"], tmp_path / "cmp.html")
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "实验对比报告" in html
    assert "实验A" in html
    assert "实验B" in html
    assert "全局排名" in html
