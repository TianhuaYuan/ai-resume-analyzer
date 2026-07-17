"""并发版实验框架 — 用 asyncio.gather 并发跑 QA，单组耗时从 ~8min 降到 ~1min。

用法：python run_concurrent.py --phase 4
      python run_concurrent.py --phase 3 --resume  # 从断点续跑
"""
import argparse
import asyncio
import itertools
import sys
from dataclasses import replace
from pathlib import Path

# 添加 backend 目录到 sys.path，以便导入 core、services 等模块
backend_dir = str(Path(__file__).parent.parent)
sys.path.insert(0, backend_dir)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.rag_params import (
    PHASE3_GRID,
    PHASE4_THRESHOLDS, PHASE6_TEMPERATURES, RagParams,
)
from rag_tuning.evaluate import (
    load_golden_set, load_resume_texts, _resume_id_map,
    evaluate_one, aggregate_metrics, save_results, print_metrics, print_table, _load_best, _load_results_list,
    rebuild_all_indices,
)

CONCURRENCY = 10  # 同时跑 10 条 QA


async def run_experiment_concurrent(
    golden_set, id_map, resume_texts, p, label="", rebuild=True,
):
    """并发版实验：用 semaphore 限制并发数"""
    errors = p.validate()
    if errors:
        return {"error": "; ".join(errors), "label": label, "params": str(p)}, []

    if rebuild:
        await rebuild_all_indices(resume_texts, id_map, p)

    sem = asyncio.Semaphore(CONCURRENCY)
    results = [None] * len(golden_set)

    async def _eval_one(idx, qa):
        async with sem:
            r = await evaluate_one(qa, id_map, p)
            results[idx] = r

    tasks = [_eval_one(i, qa) for i, qa in enumerate(golden_set)]
    await asyncio.gather(*tasks)

    # 进度输出
    answered = sum(1 for r in results if r and not r["is_reject"])
    avg = sum(r["score"] for r in results if r) / max(len(results), 1)
    print(f"  done: avg={avg:.3f}  answered={answered}/{len(results)}")

    agg = aggregate_metrics([r for r in results if r], label, p)
    return agg, [r for r in results if r]


async def run_phase3_concurrent(golden_set, id_map, resume_texts):
    best = _load_best("phase2") or _load_best("phase1")
    base_p = RagParams()
    if best:
        for k in ["chunk_size", "overlap", "rrf_k", "hybrid_top_k", "rerank_truncation"]:
            if k in best.get("params", {}):
                base_p = replace(base_p, **{k: best["params"][k]})

    results = _load_results_list("phase3")
    done_labels = {r["label"] for r in results}
    combos = [(ri, rf) for ri, rf in itertools.product(
        PHASE3_GRID["rerank_input_top_k"], PHASE3_GRID["rerank_final_top_k"]
    ) if rf <= ri]

    print(f"\n{'='*60}")
    print(f"Phase 3: rerank_input x rerank_final ({len(combos)} combos, concurrency={CONCURRENCY})")
    print(f"{'='*60}")

    for i, (ri, rf) in enumerate(combos):
        label = f"ri{ri}_rf{rf}"
        if label in done_labels:
            print(f"[{i+1}/{len(combos)}] {label} SKIP")
            continue
        p = replace(base_p, rerank_input_top_k=ri, rerank_final_top_k=rf)
        print(f"[{i+1}/{len(combos)}] {label} ...", flush=True)
        agg, details = await run_experiment_concurrent(
            golden_set, id_map, resume_texts, p, label=label, rebuild=False,
        )
        results.append(agg)
        save_results("phase3", results)
        print_metrics(agg)

    results.sort(key=lambda r: r.get("composite", 0), reverse=True)
    save_results("phase3", results)
    print_table(results, "Phase 3 Final")
    return results


async def run_phase4_concurrent(golden_set, id_map, resume_texts):
    best = _load_best("phase3") or _load_best("phase2") or _load_best("phase1")
    base_p = RagParams()
    if best:
        for k in ["chunk_size", "overlap", "rrf_k", "hybrid_top_k", "rerank_truncation",
                   "rerank_input_top_k", "rerank_final_top_k"]:
            if k in best.get("params", {}):
                base_p = replace(base_p, **{k: best["params"][k]})

    results = _load_results_list("phase4")
    done_labels = {r["label"] for r in results}

    print(f"\n{'='*60}")
    print(f"Phase 4: reject_threshold scan ({len(PHASE4_THRESHOLDS)} values, concurrency={CONCURRENCY})")
    print(f"{'='*60}")

    for i, thresh in enumerate(PHASE4_THRESHOLDS):
        label = f"thresh={thresh}"
        if label in done_labels:
            print(f"[{i+1}/{len(PHASE4_THRESHOLDS)}] {label} SKIP")
            continue
        p = replace(base_p, reject_threshold=thresh)
        print(f"[{i+1}/{len(PHASE4_THRESHOLDS)}] {label} ...", flush=True)
        agg, details = await run_experiment_concurrent(
            golden_set, id_map, resume_texts, p, label=label, rebuild=False,
        )
        results.append(agg)
        save_results("phase4", results)
        print_metrics(agg)

    results.sort(key=lambda r: r.get("composite", 0), reverse=True)
    save_results("phase4", results)
    print_table(results, "Phase 4 Final")
    return results


async def run_phase6_concurrent(golden_set, id_map, resume_texts):
    best = _load_best("phase4") or _load_best("phase3")
    base_p = RagParams()
    if best:
        for k in ["chunk_size", "overlap", "rrf_k", "hybrid_top_k", "rerank_truncation",
                   "rerank_input_top_k", "rerank_final_top_k", "reject_threshold"]:
            if k in best.get("params", {}):
                base_p = replace(base_p, **{k: best["params"][k]})

    results = _load_results_list("phase6")
    done_labels = {r["label"] for r in results}

    print(f"\n{'='*60}")
    print(f"Phase 6: temperature scan ({PHASE6_TEMPERATURES}, concurrency={CONCURRENCY})")
    print(f"{'='*60}")

    for i, temp in enumerate(PHASE6_TEMPERATURES):
        label = f"temp={temp}"
        if label in done_labels:
            print(f"[{i+1}/{len(PHASE6_TEMPERATURES)}] {label} SKIP")
            continue
        p = replace(base_p, generate_temperature=temp)
        print(f"[{i+1}/{len(PHASE6_TEMPERATURES)}] {label} ...", flush=True)
        agg, details = await run_experiment_concurrent(
            golden_set, id_map, resume_texts, p, label=label, rebuild=False,
        )
        results.append(agg)
        save_results("phase6", results)
        print_metrics(agg)

    results.sort(key=lambda r: r.get("composite", 0), reverse=True)
    save_results("phase6", results)
    print_table(results, "Phase 6 Final")
    return results


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, choices=[3, 4, 5, 6])
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()

    global CONCURRENCY
    CONCURRENCY = args.concurrency

    golden_set = load_golden_set()
    resume_files = sorted(set(qa["resume_file"] for qa in golden_set))
    resume_texts = load_resume_texts(resume_files)
    id_map = _resume_id_map(golden_set)

    if args.phase == 3:
        await run_phase3_concurrent(golden_set, id_map, resume_texts)
    elif args.phase == 4:
        await run_phase4_concurrent(golden_set, id_map, resume_texts)
    elif args.phase == 6:
        await run_phase6_concurrent(golden_set, id_map, resume_texts)


if __name__ == "__main__":
    asyncio.run(main())
