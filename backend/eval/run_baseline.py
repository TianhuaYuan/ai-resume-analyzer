"""
4 组 Baseline 对照实验，产生面试用的对比矩阵。

实验组:
  ① 纯向量检索（基线）— Bi-Encoder 余弦相似度
  ② ① + BM25 混合检索 — RRF 融合粗排
  ③ ② + Rerank 精排 — Cross-Encoder 截断 top5
  ④ ③ + Query 改写 — 完整 ask_question 流水线

用法:
    python -m eval.run_baseline --resume-id 1
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.rag_service import (
    _vector_search,
    hybrid_search,
    rerank,
    ask_question,
    rewrite_query,
)
from eval.evaluate import (
    EvalCase,
    EvalResult,
    load_golden_set,
    calc_recall_at_k,
    calc_mrr,
    calc_precision_at_k,
    calc_reject_accuracy,
    calc_answer_hit_rate,
    calc_avg_latency,
)


logger = logging.getLogger(__name__)

# Windows GBK 终端兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── 实验运行器 ─────────────────────────────────────────────

@dataclass
class ExperimentReport:
    name: str
    metrics: dict = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)
    duration_s: float = 0


async def run_experiment_dense(
    resume_id: int, cases: list[EvalCase],
) -> ExperimentReport:
    """实验①：纯向量检索"""
    results: list[EvalResult] = []
    t0 = time.perf_counter()
    for case in cases:
        start = time.perf_counter()
        try:
            chunks = await _vector_search(resume_id, case.question, top_k=10)
        except Exception as e:
            logger.warning("实验①异常 case=%s: %s", case.id, e)
            chunks = []
        elapsed = (time.perf_counter() - start) * 1000
        results.append(EvalResult(
            case=case,
            retrieved_indices=[c["chunk_index"] for c in chunks],
            is_rejected=len(chunks) == 0,
            elapsed_ms=elapsed,
        ))

    metrics = _compute_retrieval_metrics(results, cases)
    return ExperimentReport(
        name="① 纯向量检索（基线）",
        metrics=metrics,
        results=results,
        duration_s=time.perf_counter() - t0,
    )


async def run_experiment_hybrid(
    resume_id: int, cases: list[EvalCase],
) -> ExperimentReport:
    """实验②：纯向量 + BM25 混合检索"""
    results: list[EvalResult] = []
    t0 = time.perf_counter()
    for case in cases:
        start = time.perf_counter()
        try:
            chunks = await hybrid_search(resume_id, case.question, top_k=10)
        except Exception as e:
            logger.warning("实验②异常 case=%s: %s", case.id, e)
            chunks = []
        elapsed = (time.perf_counter() - start) * 1000
        results.append(EvalResult(
            case=case,
            retrieved_indices=[c["chunk_index"] for c in chunks],
            is_rejected=len(chunks) == 0,
            elapsed_ms=elapsed,
        ))

    metrics = _compute_retrieval_metrics(results, cases)
    return ExperimentReport(
        name="② ① + BM25 混合检索",
        metrics=metrics,
        results=results,
        duration_s=time.perf_counter() - t0,
    )


async def run_experiment_rerank(
    resume_id: int, cases: list[EvalCase],
) -> ExperimentReport:
    """实验③：混合检索 + Rerank 精排"""
    results: list[EvalResult] = []
    t0 = time.perf_counter()
    for case in cases:
        start = time.perf_counter()
        try:
            chunks = await hybrid_search(resume_id, case.question, top_k=20)
            if chunks:
                chunks = await rerank(case.question, chunks, top_k=5)
        except Exception as e:
            logger.warning("实验③异常 case=%s: %s", case.id, e)
            chunks = []
        elapsed = (time.perf_counter() - start) * 1000
        results.append(EvalResult(
            case=case,
            retrieved_indices=[c["chunk_index"] for c in chunks],
            answer="",  # 实验③只测检索，不生成答案
            is_rejected=len(chunks) == 0,
            elapsed_ms=elapsed,
        ))

    metrics = _compute_retrieval_metrics(results, cases)
    return ExperimentReport(
        name="③ ② + Rerank 精排",
        metrics=metrics,
        results=results,
        duration_s=time.perf_counter() - t0,
    )


async def run_experiment_full(
    resume_id: int, cases: list[EvalCase],
) -> ExperimentReport:
    """实验④：完整流水线（Query 改写 + 混合检索 + Rerank + 生成）"""
    results: list[EvalResult] = []
    t0 = time.perf_counter()
    for case in cases:
        start = time.perf_counter()
        try:
            answer, chunks = await ask_question(resume_id, case.question)
        except Exception as e:
            logger.warning("实验④异常 case=%s: %s", case.id, e)
            answer, chunks = "", []
        elapsed = (time.perf_counter() - start) * 1000
        # 拒答判断：full pipeline 可能返回拒答话术
        is_rejected = bool(chunks) is False or "未提及" in answer or "抱歉" in answer
        results.append(EvalResult(
            case=case,
            retrieved_indices=[c["chunk_index"] for c in chunks],
            answer=answer,
            is_rejected=is_rejected,
            elapsed_ms=elapsed,
        ))

    metrics = _compute_full_metrics(results, cases)
    return ExperimentReport(
        name="④ ③ + Query 改写（完整版）",
        metrics=metrics,
        results=results,
        duration_s=time.perf_counter() - t0,
    )


# ── 指标辅助 ──────────────────────────────────────────────

def _compute_retrieval_metrics(results: list[EvalResult], cases: list[EvalCase]) -> dict:
    """纯检索指标（实验①②③ 公用）"""
    return OrderedDict({
        "Recall@3": f"{calc_recall_at_k(results, 3):.3f}",
        "Recall@5": f"{calc_recall_at_k(results, 5):.3f}",
        "Recall@10": f"{calc_recall_at_k(results, 10):.3f}",
        "MRR": f"{calc_mrr(results):.3f}",
        "Precision@5": f"{calc_precision_at_k(results, 5):.3f}",
        "avg_latency_ms": f"{calc_avg_latency(results):.0f}",
    })


def _compute_full_metrics(results: list[EvalResult], cases: list[EvalCase]) -> dict:
    """全链路指标（实验④）"""
    m = _compute_retrieval_metrics(results, cases)
    m["answer_hit_rate"] = f"{calc_answer_hit_rate(results):.3f}"
    m["reject_accuracy"] = f"{calc_reject_accuracy(results):.3f}"
    # 保持字段顺序合理
    ordered = OrderedDict()
    for k in ["Recall@3", "Recall@5", "Recall@10", "MRR", "Precision@5",
              "answer_hit_rate", "reject_accuracy", "avg_latency_ms"]:
        if k in m:
            ordered[k] = m[k]
    return ordered


# ── 报告输出 ──────────────────────────────────────────────

def print_matrix(reports: list[ExperimentReport]):
    """打印 Baseline 对照矩阵（面试用）"""
    # 收集所有指标名
    all_keys: list[str] = []
    seen = set()
    for r in reports:
        for k in r.metrics:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    # 表头
    header = f"{'指标':<22s}" + "".join(f"{r.name:<30s}" for r in reports)
    sep = "─" * len(header)
    print(f"\n{sep}")
    print("  🔴 Baseline 对照矩阵（50 条 Golden Set）")
    print(sep)
    print(header)
    print(sep)

    for key in all_keys:
        row = f"  {key:<20s}"
        for r in reports:
            row += f"  {r.metrics.get(key, 'N/A'):<28s}"
        print(row)

    print(sep)
    for r in reports:
        print(f"  {r.name}: {r.duration_s:.0f}s")


# ── 结果持久化 ────────────────────────────────────────────

def save_results(reports: list[ExperimentReport], path: str):
    """保存完整评估结果到 JSON"""
    out = {}
    for r in reports:
        out[r.name] = {
            "metrics": dict(r.metrics),
            "duration_s": r.duration_s,
            "per_case": [
                {
                    "id": res.case.id,
                    "question": res.case.question,
                    "category": res.case.category,
                    "answerable": res.case.answerable,
                    "retrieved": res.retrieved_indices,
                    "expected": res.case.relevant_chunk_indices,
                    "is_rejected": res.is_rejected,
                    "elapsed_ms": res.elapsed_ms,
                }
                for res in r.results
            ],
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存: {path}")


# ── CLI ───────────────────────────────────────────────────

async def _run_exp_across_resumes(
    exp_fn,  # async (resume_id, cases) -> ExperimentReport
    group_map: dict[int, list[EvalCase]],
    label: str,
) -> ExperimentReport:
    """跨多简历跑同一实验，合并结果和指标"""
    all_results: list[EvalResult] = []
    t0 = time.perf_counter()
    for rid, cases in group_map.items():
        print(f"    resume_{rid} ({len(cases)} 条)...", end=" ")
        report = await exp_fn(rid, cases)
        all_results.extend(report.results)
        print(f"{report.duration_s:.0f}s")

    # 用合并后的 results 重新算指标
    flat_cases = [r.case for r in all_results]
    if hasattr(exp_fn, '__name__') and 'full' in exp_fn.__name__:
        metrics = _compute_full_metrics(all_results, flat_cases)
    else:
        metrics = _compute_retrieval_metrics(all_results, flat_cases)

    return ExperimentReport(
        name=label,
        metrics=metrics,
        results=all_results,
        duration_s=time.perf_counter() - t0,
    )


async def main():
    parser = argparse.ArgumentParser(description="RAG Baseline 对照实验")
    parser.add_argument("--resume-id", type=int, default=None, help="指定简历 ID，不传则跑 golden set 中所有简历")
    parser.add_argument("--golden-set", type=str, default=None)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    all_cases = load_golden_set(args.golden_set, resume_id=args.resume_id)
    group_map: dict[int, list[EvalCase]] = {}
    for c in all_cases:
        group_map.setdefault(c.resume_id, []).append(c)

    print(f"加载 Golden Set: {len(all_cases)} 条 (可回答: {sum(1 for c in all_cases if c.answerable)}, "
        f"拒答: {sum(1 for c in all_cases if not c.answerable)})")
    print(f"覆盖简历: {list(group_map.keys())}\n")

    reports: list   [ExperimentReport] = []

    # 实验① 纯向量
    print("▶ 实验① 纯向量检索...")
    r = await _run_exp_across_resumes(run_experiment_dense, group_map, "① 纯向量检索（基线）")
    reports.append(r)
    print(f"  总计 {r.duration_s:.0f}s")

    # 实验② 混合检索
    print("▶ 实验② +BM25 混合检索...")
    r = await _run_exp_across_resumes(run_experiment_hybrid, group_map, "② ① + BM25 混合检索")
    reports.append(r)
    print(f"  总计 {r.duration_s:.0f}s")

    # 实验③ Rerank
    print("▶ 实验③ +Rerank 精排...")
    r = await _run_exp_across_resumes(run_experiment_rerank, group_map, "③ ② + Rerank 精排")
    reports.append(r)
    print(f"  总计 {r.duration_s:.0f}s")

    # 实验④ 完整流水线
    print("▶ 实验④ 完整流水线...")
    r = await _run_exp_across_resumes(run_experiment_full, group_map, "④ ③ + Query 改写（完整版）")
    reports.append(r)
    print(f"  总计 {r.duration_s:.0f}s")

    # 输出矩阵
    print_matrix(reports)

    # 保存
    output = args.output or str(Path(__file__).parent / "baseline_results.json")
    save_results(reports, output)


if __name__ == "__main__":
    asyncio.run(main())
