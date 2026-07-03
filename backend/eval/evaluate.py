"""
评估脚本：加载 Golden Set，跑检索/问答流程，计算 Recall@K / MRR / Precision@K / 拒答准确率。

用法：
    python -m eval.evaluate                          # 默认：全链路评估
    python -m eval.evaluate --mode retrieval         # 仅检索评估
    python -m eval.evaluate --mode full              # 端到端问答评估
    python -m eval.evaluate --resume-id 1            # 指定简历 ID
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

# 确保 backend 在 sys.path 上
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows GBK 终端兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services.rag_service import (
    _vector_search,
    hybrid_search,
    rerank,
    ask_question,
    process_resume,
    chunk_by_sections,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("eval")


# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class EvalCase:
    id: int
    resume_id: int
    category: str
    question: str
    relevant_chunk_indices: list[int]
    keywords: list[str]
    answerable: bool


@dataclass
class EvalResult:
    case: EvalCase
    retrieved_indices: list[int] = field(default_factory=list)
    answer: str = ""
    elapsed_ms: float = 0
    is_rejected: bool = False
    # 逐条调试信息
    debug: dict = field(default_factory=dict)


# ── 指标计算 ──────────────────────────────────────────────

def calc_recall_at_k(results: list[EvalResult], k: int) -> float:
    """Recall@K：有多少相关 chunk 出现在前 K 个结果里"""
    recalls = []
    for r in results:
        if not r.case.answerable or not r.case.relevant_chunk_indices:
            continue
        if not r.retrieved_indices:
            recalls.append(0.0)
            continue
        top_k = r.retrieved_indices[:k]
        hits = len(set(top_k) & set(r.case.relevant_chunk_indices))
        recalls.append(hits / len(r.case.relevant_chunk_indices))
    return sum(recalls) / len(recalls) if recalls else 0.0


def calc_precision_at_k(results: list[EvalResult], k: int) -> float:
    """Precision@K：前 K 个结果中相关 chunk 的比例"""
    precisions = []
    for r in results:
        if not r.case.answerable or not r.case.relevant_chunk_indices:
            continue
        if not r.retrieved_indices:
            precisions.append(0.0)
            continue
        top_k = r.retrieved_indices[:k]
        hits = len(set(top_k) & set(r.case.relevant_chunk_indices))
        precisions.append(hits / min(k, len(top_k)) if top_k else 0.0)
    return sum(precisions) / len(precisions) if precisions else 0.0


def calc_mrr(results: list[EvalResult]) -> float:
    """MRR：第一个相关 chunk 排名的倒数均值"""
    rr_values = []
    for r in results:
        if not r.case.answerable or not r.case.relevant_chunk_indices:
            continue
        relevant = set(r.case.relevant_chunk_indices)
        for rank, idx in enumerate(r.retrieved_indices, start=1):
            if idx in relevant:
                rr_values.append(1.0 / rank)
                break
        else:
            rr_values.append(0.0)
    return sum(rr_values) / len(rr_values) if rr_values else 0.0


def calc_reject_accuracy(results: list[EvalResult]) -> float:
    """拒答准确率：不可回答的问题中，系统正确拒答的比例"""
    reject_cases = [r for r in results if not r.case.answerable]
    if not reject_cases:
        return 1.0
    correct = sum(1 for r in reject_cases if r.is_rejected)
    return correct / len(reject_cases)


def calc_answer_hit_rate(results: list[EvalResult]) -> float:
    """答案命中率：可回答问题中，答案包含至少一个关键词的比例（粗略的语义相关度代理）"""
    answerable = [r for r in results if r.case.answerable]
    if not answerable:
        return 1.0
    hits = 0
    for r in answerable:
        if not r.answer:
            continue
        answer_lower = r.answer.lower()
        if any(kw.lower() in answer_lower for kw in r.case.keywords):
            hits += 1
    return hits / len(answerable)


def calc_avg_latency(results: list[EvalResult]) -> float:
    """平均耗时 (ms)"""
    latencies = [r.elapsed_ms for r in results if r.elapsed_ms > 0]
    return sum(latencies) / len(latencies) if latencies else 0.0


# ── 报告 ──────────────────────────────────────────────────

def print_report(results: list[EvalResult], title: str = "评估报告") -> dict:
    """打印评估结果，返回指标 dict 供 Baseline 矩阵汇总用"""
    answerable = [r for r in results if r.case.answerable]
    reject = [r for r in results if not r.case.answerable]

    metrics = OrderedDict({
        "total_cases": len(results),
        "answerable": len(answerable),
        "reject_cases": len(reject),
        # 检索指标
        "Recall@3": f"{calc_recall_at_k(results, 3):.3f}",
        "Recall@5": f"{calc_recall_at_k(results, 5):.3f}",
        "Recall@10": f"{calc_recall_at_k(results, 10):.3f}",
        "MRR": f"{calc_mrr(results):.3f}",
        "Precision@5": f"{calc_precision_at_k(results, 5):.3f}",
        # 生成指标
        "answer_hit_rate": f"{calc_answer_hit_rate(results):.3f}",
        "reject_accuracy": f"{calc_reject_accuracy(results):.3f}",
        # 性能
        "avg_latency_ms": f"{calc_avg_latency(results):.0f}",
    })

    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    for key, val in metrics.items():
        print(f"  {key:<20s} : {val}")
    print(f"{'='*60}\n")

    return metrics


# ── 加载 Golden Set ──────────────────────────────────────

def load_golden_set(path: str | None = None, resume_id: int | None = None) -> list[EvalCase]:
    if path is None:
        path = str(Path(__file__).parent / "golden_set.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    cases = [EvalCase(**item) for item in raw]
    if resume_id is not None:
        cases = [c for c in cases if c.resume_id == resume_id]
    return cases


# ── 检索评估模式 ──────────────────────────────────────────

async def run_retrieval_eval(
    resume_id: int,
    cases: list[EvalCase],
    mode: str = "hybrid",  # "dense" | "hybrid"
) -> list[EvalResult]:
    """仅评估检索阶段：不调 LLM 生成，只对比检索 chunk 和标注"""
    results: list[EvalResult] = []
    for i, case in enumerate(cases):
        start = time.perf_counter()
        try:
            if mode == "dense":
                chunks = await _vector_search(resume_id, case.question, top_k=10)
            else:
                chunks = await hybrid_search(resume_id, case.question, top_k=10)
        except Exception as e:
            logger.error("Case %d failed: %s", case.id, e)
            chunks = []

        elapsed = (time.perf_counter() - start) * 1000
        retrieved = [c["chunk_index"] for c in chunks]

        results.append(EvalResult(
            case=case,
            retrieved_indices=retrieved,
            is_rejected=len(chunks) == 0,
            elapsed_ms=elapsed,
            debug={"n_chunks": len(chunks), "mode": mode},
        ))

        # 进度条
        if (i + 1) % 10 == 0:
            print(f"  [{i + 1}/{len(cases)}] done")

    return results


# ── 全链路评估模式 ────────────────────────────────────────

async def run_full_eval(
    resume_id: int,
    cases: list[EvalCase],
) -> list[EvalResult]:
    """端到端评估：走完整 ask_question 流水线"""
    results: list[EvalResult] = []
    for i, case in enumerate(cases):
        start = time.perf_counter()
        try:
            answer, chunks = await ask_question(resume_id, case.question)
        except Exception as e:
            logger.error("Case %d failed: %s", case.id, e)
            answer, chunks = "", []

        elapsed = (time.perf_counter() - start) * 1000
        retrieved = [c["chunk_index"] for c in chunks]
        is_rejected = "未提及" in answer or "抱歉" in answer

        results.append(EvalResult(
            case=case,
            retrieved_indices=retrieved,
            answer=answer,
            is_rejected=is_rejected,
            elapsed_ms=elapsed,
            debug={"n_chunks": len(chunks)},
        ))

        if (i + 1) % 10 == 0:
            print(f"  [{i + 1}/{len(cases)}] done")

    return results


# ── CLI ───────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="RAG 评估脚本")
    parser.add_argument("--mode", choices=["retrieval", "full"], default="full")
    parser.add_argument("--retrieval-type", choices=["dense", "hybrid"], default="hybrid")
    parser.add_argument("--resume-id", type=int, default=None, help="指定简历 ID，不传则跑 golden set 中所有简历")
    parser.add_argument("--golden-set", type=str, default=None)
    args = parser.parse_args()

    all_cases = load_golden_set(args.golden_set, resume_id=args.resume_id)
    # 按 resume_id 分组
    group_map: dict[int, list[EvalCase]] = {}
    for c in all_cases:
        group_map.setdefault(c.resume_id, []).append(c)

    print(f"加载 Golden Set: {len(all_cases)} 条")
    print(f"  可回答: {sum(1 for c in all_cases if c.answerable)}")
    print(f"  拒答:   {sum(1 for c in all_cases if not c.answerable)}")
    print(f"  覆盖简历: {list(group_map.keys())}")
    print()

    all_results: list[EvalResult] = []
    for rid, cases in group_map.items():
        print(f"▶ 评估 resume_{rid} ({len(cases)} 条)")
        if args.mode == "retrieval":
            title = f"检索评估 ({args.retrieval_type}) - resume_{rid}"
            results = await run_retrieval_eval(rid, cases, mode=args.retrieval_type)
        else:
            title = f"全链路评估 - resume_{rid}"
            results = await run_full_eval(rid, cases)
        all_results.extend(results)
        print()

    metrics = print_report(all_results, title="汇总评估报告")

    if args.mode == "retrieval":
        print_badcase_summary(all_results)

    return metrics


def print_badcase_summary(results: list[EvalResult]):
    """检索差 + 拒答错的 case"""
    print("─" * 60)
    print("  Bad Case 快速定位")
    print("─" * 60)

    for r in results:
        if r.case.answerable and r.case.relevant_chunk_indices:
            top5 = set(r.retrieved_indices[:5])
            relevant = set(r.case.relevant_chunk_indices)
            missing = relevant - top5
            if missing:
                print(f"  ⚠️  召回不足 [id={r.case.id}] \"{r.case.question[:50]}...\"")
                print(f"      漏检 chunk: {missing}, 检索到: {r.retrieved_indices[:5]}")

        if not r.case.answerable and not r.is_rejected:
            print(f"  ❌ 应拒答未拒答 [id={r.case.id}] \"{r.case.question[:50]}...\"")

    print("─" * 60)


if __name__ == "__main__":
    asyncio.run(main())
