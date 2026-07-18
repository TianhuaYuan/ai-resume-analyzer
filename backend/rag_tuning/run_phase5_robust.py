"""Phase 5: Top-3 参数组合 × 3 次重复验证（稳健版）

关键改进：
  - 每轮运行前清除所有 collection 并重建索引，避免 HNSW 段损坏
  - 并发度 5，降低 ChromaDB 压力
  - 每轮完成后立即增量保存，崩溃不丢失已有数据
  - 重置 ChromaDB 单例客户端确保干净状态

用法：cd backend && python run_phase5_robust.py
"""

import asyncio
import json
import os
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
    print_metrics,
    get_model_metadata,
    save_model_metadata,
    RESULTS_DIR,
)
import services.rag.clients as rag_clients
import services.rag.retrieval as rag_retrieval
from services.rag.chunking import chunk_by_sections
from services.rag.retrieval import get_embeddings
from services.rag.clients import _collection_name, get_chroma_client

CONCURRENCY = 5
REPETITIONS = 3
PHASE5_DIR = os.path.join(RESULTS_DIR, "phase5")


def save_phase5(filename: str, data):
    os.makedirs(PHASE5_DIR, exist_ok=True)
    # 注入模型元数据
    meta = get_model_metadata()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                item["_model"] = meta
    elif isinstance(data, dict):
        data["_model"] = meta
    path = os.path.join(PHASE5_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [SAVE] {path}")


def load_phase5(filename: str):
    path = os.path.join(PHASE5_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def reset_chroma():
    """重置 ChromaDB 客户端单例，确保干净状态"""
    if rag_clients._chroma_client is not None:
        try:
            rag_clients._chroma_client.close()
        except Exception:
            pass
    rag_clients._chroma_client = None


def clear_all_collections():
    """删除所有 resume_* collection"""
    client = get_chroma_client()
    try:
        collections = client.list_collections()
        for col in collections:
            name = col.name if hasattr(col, "name") else str(col)
            if name.startswith("resume_"):
                try:
                    client.delete_collection(name)
                except Exception:
                    pass
    except Exception:
        pass


async def rebuild_all(resume_texts, id_map, p):
    """清除并重建所有简历索引"""
    print("  [REBUILD] clearing caches...", flush=True)
    rag_retrieval._bm25_indexes.clear()
    reset_chroma()
    clear_all_collections()

    client = get_chroma_client()
    print(f"  [REBUILD] rebuilding {len(resume_texts)} indices (chunk_size={p.chunk_size})...", flush=True)
    for fname, text in resume_texts.items():
        rid = id_map[fname]
        name = _collection_name(rid)

        collection = client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )
        chunks = chunk_by_sections(text, chunk_size=p.chunk_size, overlap=p.overlap)
        if not chunks:
            continue

        texts_list = [c["text"] for c in chunks]
        embeddings = await get_embeddings(texts_list, rid)

        collection.add(
            ids=[str(c["chunk_index"]) for c in chunks],
            documents=texts_list,
            embeddings=embeddings,
            metadatas=[
                {
                    "resume_id": rid,
                    "chunk_index": c["chunk_index"],
                    "section": c["section"],
                    "start_char": c["start_char"],
                    "end_char": c["end_char"],
                }
                for c in chunks
            ],
        )
        print(f"  [REBUILD] {fname}: {len(chunks)} chunks", flush=True)
    print("  [REBUILD] done", flush=True)


async def run_one_round(golden_set, id_map, p, label):
    """跑一轮 120 QA（并发），返回 (agg, details)"""
    sem = asyncio.Semaphore(CONCURRENCY)
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
    print(f"  done in {elapsed:.1f}s  avg={avg:.3f}  answered={answered}/{len(valid)}", flush=True)

    agg = aggregate_metrics(valid, label, p)
    return agg, valid


def compute_stats(runs: list[dict]) -> dict:
    """计算均值 ± 标准差"""
    stats = {}
    for metric in [
        "composite", "avg_score", "accuracy_2", "reject_f1",
        "reject_precision", "reject_recall", "hallucination_rate",
        "p50_latency_ms", "p95_latency_ms",
    ]:
        vals = [r[metric] for r in runs if metric in r]
        if vals:
            mean = statistics.mean(vals)
            std = statistics.stdev(vals) if len(vals) > 1 else 0.0
            stats[f"{metric}_mean"] = round(mean, 4)
            stats[f"{metric}_std"] = round(std, 4)
    return stats


async def main():
    total_start = time.perf_counter()

    configs = [
        {
            "id": "A_Optimal",
            "desc": "全最优参数 (cs=1200 rrf_k=100 rf=5 thresh=0.3 temp=0.1)",
            "params": replace(
                RagParams(),
                chunk_size=1200, overlap=50, rrf_k=100, hybrid_top_k=20,
                rerank_truncation=400, rerank_input_top_k=20, rerank_final_top_k=5,
                reject_threshold=0.3, generate_temperature=0.1,
            ),
        },
        {
            "id": "B_Baseline",
            "desc": "原始默认参数 (cs=500 rrf_k=60 rf=8 thresh=0.5 temp=0.3)",
            "params": RagParams(
                chunk_size=500, overlap=50, rrf_k=60, hybrid_top_k=20,
                rerank_truncation=400, rerank_input_top_k=20, rerank_final_top_k=8,
                reject_threshold=0.5, generate_temperature=0.3,
            ),
        },
        {
            "id": "C_NearOptimal",
            "desc": "全最优但温度未优化 (temp=0.3)",
            "params": replace(
                RagParams(),
                chunk_size=1200, overlap=50, rrf_k=100, hybrid_top_k=20,
                rerank_truncation=400, rerank_input_top_k=20, rerank_final_top_k=5,
                reject_threshold=0.3, generate_temperature=0.3,
            ),
        },
    ]

    print("[LOAD] Loading Golden Set ...", flush=True)
    golden_set = load_golden_set()
    print(f"   {len(golden_set)} QA pairs", flush=True)

    resume_files = sorted(set(qa["resume_file"] for qa in golden_set))
    resume_texts = load_resume_texts(resume_files)
    print(f"   {len(resume_texts)} resumes", flush=True)

    # 保存模型元数据
    save_model_metadata()

    id_map = _resume_id_map(golden_set)

    # 增量加载
    summary = load_phase5("summary.json") or {"configs": {}}
    print("[READY] Starting experiments...", flush=True)

    for cfg in configs:
        cid = cfg["id"]
        params = cfg["params"]

        print(f"\n{'=' * 65}")
        print(f"  {cid}: {cfg['desc']}")
        print(f"  {params}")
        print(f"{'=' * 65}")

        existing_runs = summary["configs"].get(cid, {}).get("runs", [])
        done_count = len(existing_runs)

        if done_count >= REPETITIONS:
            print(f"  [SKIP] {cid} 已完成 {done_count}/{REPETITIONS} 轮")
            continue

        for run_i in range(done_count, REPETITIONS):
            print(f"\n--- {cid} Run {run_i + 1}/{REPETITIONS} ---")
            label = f"{cid}_run{run_i + 1}"

            # 每轮重建索引
            t0 = time.perf_counter()
            await rebuild_all(resume_texts, id_map, params)
            print(f"  rebuild: {time.perf_counter() - t0:.1f}s")

            agg, details = await run_one_round(golden_set, id_map, params, label)
            existing_runs.append(agg)
            print_metrics(agg)

            # 增量保存
            summary["configs"][cid] = {
                "desc": cfg["desc"],
                "params": {k: v for k, v in params.__dict__.items()},
                "runs": existing_runs,
            }
            save_phase5("summary.json", summary)

            if run_i == 0:
                save_phase5(f"{cid}_details.json", details)

    # ── 最终统计 ──
    print(f"\n{'=' * 65}")
    print("  Phase 5 最终统计汇总")
    print(f"{'=' * 65}")

    final_results = []
    for cfg in configs:
        cid = cfg["id"]
        runs = summary["configs"].get(cid, {}).get("runs", [])
        if not runs:
            continue

        stats = compute_stats(runs)
        stats["config_id"] = cid
        stats["config_desc"] = cfg["desc"]
        stats["params"] = summary["configs"][cid]["params"]
        stats["runs"] = runs
        final_results.append(stats)

        print(f"\n  {cid} (n={len(runs)}):")
        for metric in ["composite", "avg_score", "reject_f1", "p95_latency_ms"]:
            mean = stats.get(f"{metric}_mean", 0)
            std = stats.get(f"{metric}_std", 0)
            print(f"    {metric:<22s}: {mean:.4f} ± {std:.4f}")

    # ── 组间对比 ──
    if len(final_results) >= 2:
        opt = next((r for r in final_results if r["config_id"] == "A_Optimal"), None)
        base = next((r for r in final_results if r["config_id"] == "B_Baseline"), None)

        if opt and base:
            print("\n  ── Optimal vs Baseline ──")
            print(f"  {'指标':<22s} {'Optimal':>12s} {'Baseline':>12s} {'Δ':>10s} {'提升%':>9s}")
            print(f"  {'─' * 67}")
            for metric in ["composite", "avg_score", "reject_f1", "p95_latency_ms"]:
                opt_val = opt.get(f"{metric}_mean", 0)
                base_val = base.get(f"{metric}_mean", 0)
                delta = opt_val - base_val
                pct = (delta / abs(base_val)) * 100 if base_val != 0 else 0
                print(f"  {metric:<22s} {opt_val:>12.4f} {base_val:>12.4f} {delta:>+10.4f} {pct:>+8.1f}%")

    # ── 变异系数 ──
    print("\n  ── 稳定性检验 (CV%) ──")
    for r in final_results:
        vals = [run["composite"] for run in r["runs"]]
        cv = statistics.stdev(vals) / statistics.mean(vals) * 100 if statistics.mean(vals) != 0 else 0
        print(f"  {r['config_id']}: composite CV = {cv:.2f}% (n={len(vals)})")

    # ── 持久化 ──
    save_phase5("phase5_final.json", final_results)
    # 注入模型元数据后写入 rag_tuning_results/phase5.json
    meta = get_model_metadata()
    for r in final_results:
        if isinstance(r, dict):
            r["_model"] = meta
    with open(os.path.join(RESULTS_DIR, "phase5.json"), "w", encoding="utf-8") as f:
        json.dump(final_results, f, ensure_ascii=False, indent=2)
    print(f"  [SAVE] {RESULTS_DIR}/phase5.json")

    total_elapsed = time.perf_counter() - total_start
    print(f"\n[DONE] Phase 5 总耗时: {total_elapsed:.1f}s ({total_elapsed / 60:.1f}min)")


if __name__ == "__main__":
    asyncio.run(main())
