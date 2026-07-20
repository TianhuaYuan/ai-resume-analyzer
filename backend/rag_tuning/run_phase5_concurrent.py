"""Phase 5: Top-3 参数组合 × 3 次重复验证（并发版）

用法：cd backend && python run_phase5_concurrent.py

三组配置：
  A - Optimal（全最优）: cs=1200 rrf_k=100 rf=5 thresh=0.3 temp=0.1
  B - Baseline（原始默认）: cs=500 rrf_k=60 rf=8 thresh=0.5 temp=0.3
  C - NearOptimal（无温度优化）: cs=1200 rrf_k=100 rf=5 thresh=0.3 temp=0.3

每组 3 次重复 → 共 9 轮，每轮 120 QA 用 Semaphore(10) 并发。
"""

import asyncio
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.rag_params import RagParams
from rag_tuning.evaluate import (
    load_golden_set,
    load_resume_texts,
    _resume_id_map,
    evaluate_one,
    aggregate_metrics,
    save_results,
    save_details,
    print_metrics,
    rebuild_all_indices,
)

CONCURRENCY = 10
REPETITIONS = 3


async def run_experiment_concurrent(
    golden_set,
    id_map,
    resume_texts,
    p,
    label="",
    rebuild=True,
    sem=None,
):
    """并发版实验：用 semaphore 限制并发数"""
    if sem is None:
        sem = asyncio.Semaphore(CONCURRENCY)

    errors = p.validate()
    if errors:
        return {"error": "; ".join(errors), "label": label, "params": str(p)}, []

    if rebuild:
        t0 = time.perf_counter()
        await rebuild_all_indices(resume_texts, id_map, p)
        print(f"  [rebuild] {time.perf_counter() - t0:.1f}s")

    results = [None] * len(golden_set)

    async def _eval_one(idx, qa):
        async with sem:
            r = await evaluate_one(qa, id_map, p)
            results[idx] = r

    t0 = time.perf_counter()
    tasks = [_eval_one(i, qa) for i, qa in enumerate(golden_set)]
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - t0

    valid = [r for r in results if r]
    answered = sum(1 for r in valid if not r["is_reject"])
    avg = sum(r["score"] for r in valid) / max(len(valid), 1)
    print(f"  done in {elapsed:.1f}s  avg={avg:.3f}  answered={answered}/{len(valid)}")

    agg = aggregate_metrics(valid, label, p)
    return agg, valid


async def main():
    total_start = time.perf_counter()

    # ── 定义 Top-3 配置 ──
    configs = [
        (
            "A_Optimal",
            "全最优参数",
            replace(
                RagParams(),
                chunk_size=1200,
                overlap=50,
                rrf_k=100,
                hybrid_top_k=20,
                rerank_truncation=400,
                rerank_input_top_k=20,
                rerank_final_top_k=5,
                reject_threshold=0.3,
                generate_temperature=0.1,
            ),
        ),
        (
            "B_Baseline",
            "原始默认参数",
            RagParams(),  # 所有默认值
        ),
        (
            "C_NearOptimal",
            "全最优但温度未优化 (temp=0.3)",
            replace(
                RagParams(),
                chunk_size=1200,
                overlap=50,
                rrf_k=100,
                hybrid_top_k=20,
                rerank_truncation=400,
                rerank_input_top_k=20,
                rerank_final_top_k=5,
                reject_threshold=0.3,
                generate_temperature=0.3,
            ),
        ),
    ]

    # ── 加载数据 ──
    print("[LOAD] Loading Golden Set ...")
    golden_set = load_golden_set()
    print(f"   共 {len(golden_set)} 条 QA")

    resume_files = sorted(set(qa["resume_file"] for qa in golden_set))
    resume_texts = load_resume_texts(resume_files)
    print(f"   共 {len(resume_texts)} 份简历")

    id_map = _resume_id_map(golden_set)

    # 全局信号量：控制跨所有运行的并发 LLM 调用数
    global_sem = asyncio.Semaphore(CONCURRENCY)

    all_phase5_results = []

    for config_id, config_desc, params in configs:
        print(f"\n{'=' * 65}")
        print(f"  {config_id}: {config_desc}")
        print(f"  {params}")
        print(f"{'=' * 65}")

        config_runs = []
        need_rebuild = True  # 每组配置首次运行重建索引

        for run_i in range(1, REPETITIONS + 1):
            print(f"\n--- {config_id} Run {run_i}/{REPETITIONS} ---")
            label = f"{config_id}_run{run_i}"

            agg, details = await run_experiment_concurrent(
                golden_set,
                id_map,
                resume_texts,
                params,
                label=label,
                rebuild=need_rebuild,
                sem=global_sem,
            )
            need_rebuild = False  # 同配置后续运行复用索引
            config_runs.append(agg)
            print_metrics(agg)

            # 首轮保存逐 QA 详情
            if run_i == 1:
                save_details(f"phase5_{config_id}", details)

        # ── 统计均值 ± 标准差 ──
        print(f"\n{'─' * 50}")
        print(f"  {config_id} 统计汇总 (n={REPETITIONS})")
        print(f"{'─' * 50}")

        stats = {
            "config_id": config_id,
            "config_desc": config_desc,
            "params": {k: v for k, v in params.__dict__.items()},
            "runs": config_runs,
        }
        for metric in [
            "composite",
            "avg_score",
            "accuracy_2",
            "reject_f1",
            "reject_precision",
            "reject_recall",
            "hallucination_rate",
            "p50_latency_ms",
            "p95_latency_ms",
        ]:
            vals = [r[metric] for r in config_runs if metric in r]
            if vals:
                mean = statistics.mean(vals)
                std = statistics.stdev(vals) if len(vals) > 1 else 0.0
                stats[f"{metric}_mean"] = round(mean, 4)
                stats[f"{metric}_std"] = round(std, 4)
                print(f"  {metric:<22s}: {mean:.4f} ± {std:.4f}")

        all_phase5_results.append(stats)

    # ── 组间对比 ──
    print(f"\n{'=' * 65}")
    print("  组间对比 (Optimal vs Baseline vs NearOptimal)")
    print(f"{'=' * 65}")

    opt = all_phase5_results[0]
    base = all_phase5_results[1]

    print(f"\n  {'指标':<22s} {'Optimal':>10s} {'Baseline':>10s} {'Δ':>10s} {'提升%':>9s}")
    print(f"  {'─' * 63}")
    for metric in ["composite", "avg_score", "reject_f1", "p95_latency_ms"]:
        opt_val = opt.get(f"{metric}_mean", 0)
        base_val = base.get(f"{metric}_mean", 0)
        delta = opt_val - base_val
        pct = (delta / abs(base_val)) * 100 if base_val != 0 else 0
        print(f"  {metric:<22s} {opt_val:>10.4f} {base_val:>10.4f} {delta:>+10.4f} {pct:>+8.1f}%")

    # ── 统计显著性（简易 t-test） ──
    print("\n  ── 简易统计检验 ──")
    for config in all_phase5_results:
        cid = config["config_id"]
        vals = [r["composite"] for r in config["runs"]]
        cv = (
            statistics.stdev(vals) / statistics.mean(vals) * 100
            if statistics.mean(vals) != 0
            else 0
        )
        print(f"  {cid}: composite CV = {cv:.2f}% (n={len(vals)})")

    # ── 持久化 ──
    save_results("phase5", all_phase5_results)

    total_elapsed = time.perf_counter() - total_start
    print(f"\n[DONE] Phase 5 总耗时: {total_elapsed:.1f}s ({total_elapsed / 60:.1f}min)")


if __name__ == "__main__":
    asyncio.run(main())
