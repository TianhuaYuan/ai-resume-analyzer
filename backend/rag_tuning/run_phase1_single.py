"""逐个运行 Phase 1 组合，增量保存结果。

用法：python run_phase1_single.py --index 5   # 运行第 5 个组合
      python run_phase1_single.py --all        # 逐个运行全部（跳过已完成）
"""
import argparse
import asyncio
import itertools
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.rag_params import PHASE1_GRID, RagParams
from rag_tuning.evaluate import (
    load_golden_set, load_resume_texts, _resume_id_map,
    run_experiment, save_results, save_details, print_metrics,
    RESULTS_DIR,
)


def get_combos():
    return [(cs, ov) for cs, ov in itertools.product(
        PHASE1_GRID["chunk_size"], PHASE1_GRID["overlap"]
    ) if ov < cs]


def load_existing():
    path = os.path.join(RESULTS_DIR, "phase1.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_incremental(all_results):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, "phase1.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)


async def run_one(index: int, golden_set, id_map, resume_texts):
    combos = get_combos()
    if index < 0 or index >= len(combos):
        print(f"Index {index} out of range (0-{len(combos)-1})")
        return

    cs, ov = combos[index]
    label = f"cs{cs}_ov{ov}"

    # Check if already done
    existing = load_existing()
    done_labels = {r["label"] for r in existing}
    if label in done_labels:
        print(f"[SKIP] {label} already done")
        return

    p = replace(RagParams(), chunk_size=cs, overlap=ov)
    print(f"\n[RUN] {label} (index={index})")
    print(f"  Params: chunk_size={cs}, overlap={ov}")

    agg, details = await run_experiment(golden_set, id_map, resume_texts, p, label=label)
    print_metrics(agg)

    # Incremental save
    existing.append(agg)
    save_incremental(existing)
    save_details(f"phase1_{label}", details)
    print(f"[SAVED] {label}")


async def run_all(golden_set, id_map, resume_texts):
    combos = get_combos()
    existing = load_existing()
    done_labels = {r["label"] for r in existing}

    remaining = [(i, cs, ov) for i, (cs, ov) in enumerate(combos)
                 if f"cs{cs}_ov{ov}" not in done_labels]

    if not remaining:
        print("All combinations already done!")
        return

    print(f"Remaining: {len(remaining)}/{len(combos)}")

    for i, cs, ov in remaining:
        label = f"cs{cs}_ov{ov}"
        p = replace(RagParams(), chunk_size=cs, overlap=ov)
        print(f"\n[RUN] {label} ({i+1}/{len(combos)})")

        agg, details = await run_experiment(golden_set, id_map, resume_texts, p, label=label)
        print_metrics(agg)

        existing.append(agg)
        save_incremental(existing)
        save_details(f"phase1_{label}", details)
        print(f"[SAVED] {label}")

    # Sort and final save
    existing.sort(key=lambda r: r.get("composite", 0), reverse=True)
    save_incremental(existing)
    print("\n=== Phase 1 Final Results ===")
    for r in existing:
        print(f"  {r['label']:<20} comp={r.get('composite',0):.4f}  avg={r.get('avg_score',0):.3f}  rej={r.get('reject_f1',0):.3f}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, help="Run single combo by index")
    parser.add_argument("--all", action="store_true", help="Run all remaining")
    args = parser.parse_args()

    golden_set = load_golden_set()
    resume_files = sorted(set(qa["resume_file"] for qa in golden_set))
    resume_texts = load_resume_texts(resume_files)
    id_map = _resume_id_map(golden_set)

    if args.index is not None:
        await run_one(args.index, golden_set, id_map, resume_texts)
    elif args.all:
        await run_all(golden_set, id_map, resume_texts)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
