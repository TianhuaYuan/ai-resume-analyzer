"""RAG 参数调优实验框架 — evaluate.py

用法：
    cd backend
    python -m rag_tuning.evaluate --phase 1          # Phase 1: chunk_size × overlap
    python -m rag_tuning.evaluate --phase 2          # Phase 2: 检索参数扫描
    python -m rag_tuning.evaluate --phase 3          # Phase 3: 精排压缩比
    python -m rag_tuning.evaluate --phase 4          # Phase 4: 拒答阈值
    python -m rag_tuning.evaluate --phase 6          # Phase 6: temperature
    python -m rag_tuning.evaluate --phase 5          # Phase 5: Top-3 全量验证
    python -m rag_tuning.evaluate --baseline         # 跑一次当前默认参数作为基线
    python -m rag_tuning.evaluate --single chunk_size=800,overlap=100  # 单组参数测试
"""

import argparse
import asyncio
import itertools
import json
import logging
import os
import re
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

logger = logging.getLogger(__name__)

# Windows GBK 兼容：强制 stdout/stderr 用 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 确保能导入 backend 包
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AsyncOpenAI

from core.config import settings
from core.rag_params import (
    PHASE1_GRID,
    PHASE2_SWEEP,
    PHASE3_GRID,
    PHASE4_THRESHOLDS,
    PHASE6_TEMPERATURES,
    RagParams,
)
from services.rag_service import (
    ask_question_p,
    chunk_by_sections,
    get_embeddings,
    get_chroma_client,
    _collection_name,
)


def get_model_metadata() -> dict:
    """获取当前实验的模型配置元数据，用于标注实验结果"""
    return {
        "chat_model": settings.CHAT_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "rerank_model": settings.RERANK_MODEL,
        "judge_model": settings.JUDGE_MODEL,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_model_metadata():
    """在实验开始时保存模型元数据文件，便于后续溯源"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    meta = get_model_metadata()
    meta["note"] = "本目录下所有实验结果均使用此模型配置生成。换模型后需重新标注或新建目录。"
    path = os.path.join(RESULTS_DIR, "_model_metadata.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[META] Model config saved to {path}")
    print(f"  Chat: {meta['chat_model']}")
    print(f"  Embedding: {meta['embedding_model']}")
    print(f"  Rerank: {meta['rerank_model']}")


# ───────────────────── 数据加载 ─────────────────────

def load_golden_set(path: str = "golden_set.json", split: str | None = None) -> list[dict]:
    """加载评测数据集，可选按 split 过滤。

    JSON 顶层结构：
      { "samples": [...], "resumes": {"1": {"file": "...", "name": "..."}} }
    每个 sample 必须有 resume_id 字段。
    返回的 list 中每条额外注入 resume_file 字段供下游使用。
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    # 从 resumes 映射构建 resume_file 查找表
    resume_map: dict[int, str] = {}
    for rid_str, info in raw.get("resumes", {}).items():
        resume_map[int(rid_str)] = info["file"]
    # 注入 resume_file 字段，可选项按 split 过滤
    samples = raw.get("samples", [])
    for s in samples:
        rid = s.get("resume_id", 0)
        if rid > 0 and rid in resume_map:
            s["resume_file"] = resume_map[rid]
    if split is not None:
        samples = [s for s in samples if s.get("split") == split]
    return samples


def load_resume_texts(resume_files: list[str], upload_dir: str = "./rag_tuning/uploads") -> dict[str, str]:
    """读取简历原文，返回 {filename: text}"""
    texts = {}
    for fname in resume_files:
        fpath = os.path.join(upload_dir, fname)
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f:
                texts[fname] = f.read()
    return texts


# ───────────────────── 索引重建 ─────────────────────

async def rebuild_index(
    resume_filename: str,
    text: str,
    resume_id: int,
    p: RagParams,
) -> int:
    """用指定 chunk_size/overlap 重建单份简历的 Chroma 索引，返回 chunk 数"""
    client = get_chroma_client()
    name = _collection_name(resume_id)
    try:
        client.delete_collection(name)
    except Exception:
        pass

    collection = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
    chunks = chunk_by_sections(text, chunk_size=p.chunk_size, overlap=p.overlap)
    if not chunks:
        return 0

    texts_list = [c["text"] for c in chunks]
    embeddings = await get_embeddings(texts_list, resume_id)

    collection.add(
        ids=[str(c["chunk_index"]) for c in chunks],
        documents=texts_list,
        embeddings=embeddings,
        metadatas=[
            {
                "resume_id": resume_id,
                "chunk_index": c["chunk_index"],
                "section": c["section"],
                "start_char": c["start_char"],
                "end_char": c["end_char"],
            }
            for c in chunks
        ],
    )
    return len(chunks)


async def rebuild_all_indices(
    resume_texts: dict[str, str],
    id_map: dict[str, int],
    p: RagParams,
) -> dict[str, int]:
    """重建所有简历索引，返回 {filename: chunk_count}"""
    counts = {}
    for fname, text in resume_texts.items():
        rid = id_map[fname]
        cnt = await rebuild_index(fname, text, rid, p)
        counts[fname] = cnt
    return counts


# ───────────────────── 评估 ─────────────────────

JUDGE_SYSTEM = (
    "你是一个简历问答评估专家。请对比标准答案和系统答案，给出 0-2 分：\n"
    "0 = 完全错误或答非所问\n"
    "1 = 部分正确（包含关键信息但不完整或有小错）\n"
    "2 = 完全正确（核心信息都对）\n"
    "只输出一个数字 0、1 或 2。"
)


_judge_client: AsyncOpenAI | None = None


def _get_judge_client() -> AsyncOpenAI:
    """Judge 客户端单例（复用 TCP 连接，避免 6720 次 TLS 握手）。"""
    global _judge_client
    if _judge_client is None:
        _judge_client = AsyncOpenAI(
            api_key=settings.JUDGE_API_KEY,
            base_url=settings.JUDGE_BASE_URL,
            timeout=30.0,
        )
    return _judge_client


async def _judge_llm_generate(system: str, user: str) -> str:
    """用 JUDGE_* 配置的独立模型打分（与回答模型分离，消除同模型偏差）。"""
    if not settings.JUDGE_ENABLED or not settings.JUDGE_API_KEY:
        raise RuntimeError("Judge 未配置，无法打分。请设置 JUDGE_ENABLED=true 和 JUDGE_API_KEY。")
    client = _get_judge_client()
    response = await client.chat.completions.create(
        model=settings.JUDGE_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        max_tokens=10,
    )
    return (response.choices[0].message.content or "").strip()


async def judge_answer(
    system_answer: str, reference_answer: str, answer_type: str,
) -> int:
    """LLM-as-Judge 打分（使用 JUDGE_* 配置的独立模型），返回 0/1/2"""
    prompt = (
        f"标准答案：{reference_answer}\n"
        f"系统答案：{system_answer}\n"
        f"问题类型：{answer_type}\n\n"
        "打分（0/1/2）："
    )
    try:
        result = await _judge_llm_generate(JUDGE_SYSTEM, prompt)
        match = re.search(r"[012]", result)
        return int(match.group()) if match else 1
    except Exception as e:
        logger.warning("Judge API call failed: %s, defaulting to score=1", e)
        return 1  # 评分失败默认给 1（不中断实验）


def check_reject(answer: str) -> bool:
    """判断系统是否拒答"""
    reject_markers = ["未提及", "找不到", "没有提到", "无法回答", "没有相关信息", "简历中未"]
    return any(m in answer for m in reject_markers)


def check_hallucination(answer: str, sources: list[dict]) -> bool:
    """占位函数：当前不参与 composite 计算（权重已降为 0）。

    旧实现只检测年份数字，纯文本幻觉完全漏检。二轮调优中不计入综合分，
    仅在报告中记录供人工审查。后续可替换为 LLM 幻觉检测。
    """
    return False  # 已弃用，不再产生假阳性信号


async def evaluate_one(
    qa: dict,
    id_map: dict[str, int],
    p: RagParams,
) -> dict:
    """评估单条 QA"""
    # resume_id=0 的跨简历题不在 tuning 集，跳过
    if qa.get("resume_id", 0) == 0:
        return {
            "qa_id": qa["id"],
            "answer": "",
            "is_reject": False,
            "should_answer": qa.get("should_answer", True),
            "reject_correct": False,
            "score": 0,
            "skip": True,
            "error": "cross-resume question (resume_id=0), not evaluated here",
        }
    resume_id = id_map.get(qa["resume_file"], 0)
    if resume_id == 0:
        return {
            "qa_id": qa["id"],
            "answer": "",
            "is_reject": False,
            "should_answer": qa.get("should_answer", True),
            "reject_correct": False,
            "score": 0,
            "skip": True,
            "error": f"unknown resume_file: {qa.get('resume_file', '')}",
        }
    question = qa["question"]

    start = time.perf_counter()
    answer, sources, timings = await ask_question_p(resume_id, question, p)
    latency_ms = (time.perf_counter() - start) * 1000

    is_reject = check_reject(answer)
    should_answer = qa.get("should_answer", True)

    result = {
        "qa_id": qa["id"],
        "answer_type": qa.get("category", "unknown"),
        "answer": answer,  # 保存答案文本，便于坏案例回溯分析
        "latency_ms": latency_ms,
        "timings": timings,
        "is_reject": is_reject,
        "should_answer": should_answer,
        "reject_correct": (not should_answer) == is_reject,
    }

    if should_answer and not is_reject:
        score = await judge_answer(answer, qa.get("reference_answer", qa.get("gold_answer", "")), qa.get("category", "unknown"))
        hallucination = check_hallucination(answer, sources)
        result["score"] = score
        result["hallucination"] = hallucination
    elif not should_answer:
        result["score"] = 2 if is_reject else 0  # 拒答正确=2, 拒答错误=0
        result["hallucination"] = False
    else:
        # should_answer=True 但被拒答
        result["score"] = 0
        result["hallucination"] = False

    return result


# QA 并发数（run_experiment 默认值）
_CONCURRENCY = 8


async def run_experiment(
    golden_set: list[dict],
    id_map: dict[str, int],
    resume_texts: dict[str, str],
    p: RagParams,
    label: str = "",
    rebuild: bool = True,
    concurrency: int | None = None,
) -> tuple[dict, list[dict]]:
    """给定一组参数，并发跑全量 Golden Set 评估。返回 (aggregate, per_qa_details)"""
    errors = p.validate()
    if errors:
        return {"error": "; ".join(errors), "label": label, "params": str(p)}, []

    if rebuild:
        await rebuild_all_indices(resume_texts, id_map, p)

    sem = asyncio.Semaphore(concurrency or _CONCURRENCY)
    results: list[dict | None] = [None] * len(golden_set)

    async def _eval(idx: int, qa: dict):
        async with sem:
            try:
                r = await evaluate_one(qa, id_map, p)
                return idx, r
            except Exception as e:
                return idx, {"skip": True, "error": str(e)}

    # 用 as_completed 实现进度输出。
    # 注意：as_completed 产出的是「等待下一个完成」的协程，并非原始 future，
    # 无法以其为 key 回查 idx。改为「任务返回 (idx, result)」，await 后直接解包。
    tasks = [asyncio.ensure_future(_eval(i, qa)) for i, qa in enumerate(golden_set)]
    done_count = 0
    for fut in asyncio.as_completed(tasks):
        idx, r = await fut
        results[idx] = r
        done_count += 1
        if r.get("skip"):
            print(f"  [WARN] QA {golden_set[idx].get('id', idx)} failed: {r.get('error')}", flush=True)
        if done_count % 10 == 0 or done_count == len(golden_set):
            valid_tmp = [x for x in results if isinstance(x, dict) and not x.get("skip")]
            avg_tmp = sum(x.get("score", 0) for x in valid_tmp) / max(len(valid_tmp), 1) if valid_tmp else 0
            print(f"  [{done_count}/{len(golden_set)}] avg={avg_tmp:.3f}", flush=True)

    valid = [r for r in results if isinstance(r, dict) and not r.get("skip")]

    agg = aggregate_metrics(valid, label, p)
    return agg, valid


def aggregate_metrics(results: list[dict], label: str = "", p: RagParams = None) -> dict:
    """汇总评估指标（跳过 skip=True 的条目）"""
    total = len(results)
    skipped = len([r for r in results if r.get("skip", False)])
    results = [r for r in results if not r.get("skip", False)]
    answered = [r for r in results if not r["is_reject"]]
    rejected = [r for r in results if r["is_reject"]]
    should_reject = [r for r in results if not r["should_answer"]]
    should_answer = [r for r in results if r["should_answer"]]

    # 准确率（已回答的）
    scores = [r["score"] for r in answered]
    avg_score = statistics.mean(scores) if scores else 0
    accuracy_2 = sum(1 for s in scores if s == 2) / max(len(scores), 1)

    # 拒答指标
    reject_correct = sum(1 for r in results if r["reject_correct"])
    reject_accuracy = reject_correct / len(results) if results else 0

    # 拒答 F1
    true_positive_reject = sum(1 for r in should_reject if r["is_reject"])  # 应拒→实拒
    false_positive_reject = sum(1 for r in should_answer if r["is_reject"])  # 不应拒→实拒
    false_negative_reject = sum(1 for r in should_reject if not r["is_reject"])  # 应拒→未拒

    reject_precision = true_positive_reject / max(true_positive_reject + false_positive_reject, 1)
    reject_recall = true_positive_reject / max(true_positive_reject + false_negative_reject, 1)
    reject_f1 = 2 * reject_precision * reject_recall / max(reject_precision + reject_recall, 0.001)

    # 幻觉率
    hallucinations = sum(1 for r in answered if r.get("hallucination", False))
    hallucination_rate = hallucinations / max(len(answered), 1)

    # 延迟
    latencies = [r["latency_ms"] for r in results]
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

    # 综合分数：答案质量(0-1归一化) × 0.75 + 拒答决策质量 × 0.25
    # 权重匹配 tuning 集问题分布（rejection 类占 20%，非 rejection 占 80%）
    # 避免拒答类过度加权导致选出的参数牺牲事实回答能力
    norm_score = avg_score / 2.0  # avg_score 范围 0-2，归一化到 0-1
    composite = 0.75 * norm_score + 0.25 * reject_f1

    # 按类别分解
    categories = {}
    for r in results:
        cat = r.get("answer_type", "unknown")
        categories.setdefault(cat, []).append(r)
    category_metrics = {}
    for cat, cat_results in categories.items():
        cat_scores = [r["score"] for r in cat_results if not r["is_reject"] and "score" in r]
        cat_avg = statistics.mean(cat_scores) if cat_scores else 0
        cat_count = len(cat_results)
        category_metrics[cat] = {
            "count": cat_count,
            "avg_score": round(cat_avg, 3),
        }

    return {
        "label": label,
        "params": p.__dict__ if p else {},
        "total": total,
        "skipped": skipped,
        "per_category": category_metrics,
        "answered_count": len(answered),
        "rejected_count": len(rejected),
        "avg_score": round(avg_score, 3),
        "accuracy_2": round(accuracy_2, 3),
        "reject_accuracy": round(reject_accuracy, 3),
        "reject_f1": round(reject_f1, 3),
        "reject_precision": round(reject_precision, 3),
        "reject_recall": round(reject_recall, 3),
        "hallucination_rate": round(hallucination_rate, 3),
        "p50_latency_ms": round(p50, 0),
        "p95_latency_ms": round(p95, 0),
        "composite": round(composite, 4),
    }


# ───────────────────── 各 Phase 执行器 ─────────────────────

def _resume_id_map(golden_set: list[dict]) -> dict[str, int]:
    """从 Golden Set 构建 filename→id 映射（使用数据集中定义的 resume_id）"""
    files_ids = {}
    for qa in golden_set:
        fname = qa.get("resume_file", "")
        rid = qa.get("resume_id", 0)
        if fname and rid > 0:
            files_ids[fname] = rid
    return files_ids


async def run_baseline(golden_set, id_map, resume_texts):
    """跑当前默认参数作为基线"""
    p = RagParams()
    print(f"\n{'='*60}")
    print(f"BASELINE — 默认参数: {p}")
    print(f"{'='*60}")
    agg, details = await run_experiment(golden_set, id_map, resume_texts, p, label="baseline", concurrency=3)
    print_metrics(agg)
    save_results("baseline", [agg])
    save_details("baseline", details)
    return agg


async def run_phase1(golden_set, id_map, resume_texts):
    """Phase 1: chunk_size × overlap 网格粗扫"""
    results = []
    combos = list(itertools.product(PHASE1_GRID["chunk_size"], PHASE1_GRID["overlap"]))
    total = len([c for c in combos if c[1] < c[0]])

    print(f"\n{'='*60}")
    print(f"Phase 1: chunk_size × overlap 网格 ({total} 组合)")
    print(f"{'='*60}")

    for i, (cs, ov) in enumerate(combos):
        if ov >= cs:
            continue
        p = replace(RagParams(), chunk_size=cs, overlap=ov)
        label = f"cs{cs}_ov{ov}"
        print(f"\n[{i+1}/{total}] {label} ...", end=" ", flush=True)
        agg, details = await run_experiment(golden_set, id_map, resume_texts, p, label=label, concurrency=3)
        results.append(agg)
        save_details(f"phase1_{label}", details)
        print(f"acc={agg.get('accuracy_2', 0):.3f}  rej_f1={agg.get('reject_f1', 0):.3f}  p95={agg.get('p95_latency_ms', 0):.0f}ms")

    results.sort(key=lambda r: r.get("composite", 0), reverse=True)
    save_results("phase1", results)
    print_table(results, "Phase 1 结果排序")
    return results


async def run_phase2(golden_set, id_map, resume_texts):
    """Phase 2: 单变量扫描（rrf_k, hybrid_top_k, rerank_truncation）"""
    all_results = []

    # 先用 Phase 1 最优参数重建索引（如果存在）
    best = _load_best("phase1")
    base_p = RagParams()
    if best:
        base_p = replace(base_p, chunk_size=best["params"]["chunk_size"], overlap=best["params"]["overlap"])
        print(f"Phase 2 使用 Phase 1 最优: cs={base_p.chunk_size}, ov={base_p.overlap}")

    for param_name, values in PHASE2_SWEEP.items():
        results = []
        print(f"\n{'='*60}")
        print(f"Phase 2: 扫描 {param_name} = {values}")
        print(f"{'='*60}")

        for i, val in enumerate(values):
            if param_name == "rerank_truncation" and val == 0:
                val = 999999  # 不截断
            kwargs = {param_name: val}
            p = replace(base_p, **kwargs)
            label = f"{param_name}={val}"
            print(f"[{i+1}/{len(values)}] {label} ...", end=" ", flush=True)
            # 检索参数变了不需要重建索引（除非 chunk_size/overlap 变了）
            agg, details = await run_experiment(golden_set, id_map, resume_texts, p, label=label, rebuild=False)
            results.append(agg)
            all_results.append(agg)
            save_details(f"phase2_{label}", details)
            print(f"acc={agg.get('accuracy_2', 0):.3f}  rej_f1={agg.get('reject_f1', 0):.3f}")

        save_results(f"phase2_{param_name}", results)

    all_results.sort(key=lambda r: r.get("composite", 0), reverse=True)
    save_results("phase2", all_results)
    return all_results


async def run_phase3(golden_set, id_map, resume_texts):
    """Phase 3: 精排压缩比网格搜索"""
    best = _load_best("phase2") or _load_best("phase1")
    base_p = RagParams()
    if best:
        for k in ["chunk_size", "overlap", "rrf_k", "hybrid_top_k", "rerank_truncation"]:
            if k in best["params"]:
                base_p = replace(base_p, **{k: best["params"][k]})

    results = []
    combos = list(itertools.product(PHASE3_GRID["rerank_input_top_k"], PHASE3_GRID["rerank_final_top_k"]))
    total = len([c for c in combos if c[1] <= c[0]])

    print(f"\n{'='*60}")
    print(f"Phase 3: rerank_input × rerank_final ({total} 组合)")
    print(f"{'='*60}")

    for i, (ri, rf) in enumerate(combos):
        if rf > ri:
            continue
        p = replace(base_p, rerank_input_top_k=ri, rerank_final_top_k=rf)
        label = f"ri{ri}_rf{rf}"
        print(f"[{i+1}/{total}] {label} ...", end=" ", flush=True)
        agg, details = await run_experiment(golden_set, id_map, resume_texts, p, label=label, rebuild=False)
        results.append(agg)
        save_details(f"phase3_{label}", details)
        print(f"acc={agg.get('accuracy_2', 0):.3f}  rej_f1={agg.get('reject_f1', 0):.3f}")

    results.sort(key=lambda r: r.get("composite", 0), reverse=True)
    save_results("phase3", results)
    print_table(results, "Phase 3 结果排序")
    return results


async def run_phase4(golden_set, id_map, resume_texts):
    """Phase 4: 拒答阈值单变量扫描"""
    best = _load_best("phase3") or _load_best("phase2") or _load_best("phase1")
    base_p = RagParams()
    if best:
        for k in ["chunk_size", "overlap", "rrf_k", "hybrid_top_k", "rerank_truncation",
                   "rerank_input_top_k", "rerank_final_top_k"]:
            if k in best["params"]:
                base_p = replace(base_p, **{k: best["params"][k]})

    results = []
    print(f"\n{'='*60}")
    print(f"Phase 4: reject_threshold 扫描 {PHASE4_THRESHOLDS}")
    print(f"{'='*60}")

    for i, thresh in enumerate(PHASE4_THRESHOLDS):
        p = replace(base_p, reject_threshold=thresh)
        label = f"thresh={thresh}"
        print(f"[{i+1}/{len(PHASE4_THRESHOLDS)}] {label} ...", end=" ", flush=True)
        agg, details = await run_experiment(golden_set, id_map, resume_texts, p, label=label, rebuild=False)
        results.append(agg)
        save_details(f"phase4_{label}", details)
        print(f"acc={agg.get('accuracy_2', 0):.3f}  rej_f1={agg.get('reject_f1', 0):.3f}  rej_rate={agg.get('rejected_count', 0)}/{agg.get('total', 0)}")

    results.sort(key=lambda r: r.get("composite", 0), reverse=True)
    save_results("phase4", results)
    print_table(results, "Phase 4 结果排序")
    return results


async def run_phase6(golden_set, id_map, resume_texts):
    """Phase 6: temperature 低温锁定"""
    best = _load_best("phase4") or _load_best("phase3")
    base_p = RagParams()
    if best:
        for k in ["chunk_size", "overlap", "rrf_k", "hybrid_top_k", "rerank_truncation",
                   "rerank_input_top_k", "rerank_final_top_k", "reject_threshold"]:
            if k in best["params"]:
                base_p = replace(base_p, **{k: best["params"][k]})

    results = []
    print(f"\n{'='*60}")
    print(f"Phase 6: temperature 扫描 {PHASE6_TEMPERATURES}")
    print(f"{'='*60}")

    for i, temp in enumerate(PHASE6_TEMPERATURES):
        p = replace(base_p, generate_temperature=temp)
        label = f"temp={temp}"
        print(f"[{i+1}/{len(PHASE6_TEMPERATURES)}] {label} ...", end=" ", flush=True)
        agg, details = await run_experiment(golden_set, id_map, resume_texts, p, label=label, rebuild=False)
        results.append(agg)
        save_details(f"phase6_{label}", details)
        print(f"acc={agg.get('accuracy_2', 0):.3f}  rej_f1={agg.get('reject_f1', 0):.3f}")

    results.sort(key=lambda r: r.get("composite", 0), reverse=True)
    save_results("phase6", results)
    print_table(results, "Phase 6 结果排序")
    return results


async def run_phase5(golden_set, id_map, resume_texts):
    """Phase 5: Top-3 参数组合全量验证（3 次重复取均值±标准差）"""
    # 收集各 Phase 最优
    best_overall = _load_best("phase4") or _load_best("phase3") or _load_best("phase2") or _load_best("phase1")
    if not best_overall:
        print("没有找到之前的实验结果，请先跑 Phase 1-4")
        return []

    base_p = RagParams()
    for k, v in best_overall["params"].items():
        if hasattr(base_p, k):
            base_p = replace(base_p, **{k: v})

    print(f"\n{'='*60}")
    print("Phase 5: 最优参数 3 次重复验证")
    print(f"参数: {base_p}")
    print(f"{'='*60}")

    all_runs = []
    for run_i in range(3):
        print(f"\n--- 第 {run_i+1}/3 次 ---")
        agg, details = await run_experiment(golden_set, id_map, resume_texts, base_p, label=f"best_run{run_i+1}", concurrency=3)
        all_runs.append(agg)
        save_details(f"phase5_run{run_i+1}", details)
        print_metrics(agg)

    # 统计均值 ± 标准差
    for metric in ["accuracy_2", "reject_f1", "hallucination_rate", "p95_latency_ms", "composite"]:
        vals = [r[metric] for r in all_runs]
        mean = statistics.mean(vals)
        std = statistics.stdev(vals) if len(vals) > 1 else 0
        print(f"  {metric}: {mean:.4f} ± {std:.4f}")

    save_results("phase5", all_runs)
    return all_runs


async def run_single(golden_set, id_map, resume_texts, params_str: str):
    """单组参数快速测试"""
    pairs = params_str.split(",")
    kwargs = {}
    for pair in pairs:
        k, v = pair.split("=")
        # 类型推断
        if "." in v:
            kwargs[k.strip()] = float(v)
        else:
            kwargs[k.strip()] = int(v)

    p = replace(RagParams(), **kwargs)
    print(f"\n单组参数测试: {p}")
    agg, details = await run_experiment(golden_set, id_map, resume_texts, p, label="single")
    print_metrics(agg)
    return agg


# ───────────────────── 输出与持久化 ─────────────────────

RESULTS_DIR = "experiment_results"


def save_results(phase: str, results: list[dict]):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    # 在结果中注入模型元数据
    meta = get_model_metadata()
    for r in results:
        r["_model"] = meta
    path = os.path.join(RESULTS_DIR, f"{phase}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVE] Results saved to {path}")


def save_details(phase: str, details: list[dict]):
    """保存每条 QA 的详细结果，用于后续分析"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    # 在详情中注入模型元数据
    meta = get_model_metadata()
    for d in details:
        d["_model"] = meta
    path = os.path.join(RESULTS_DIR, f"{phase}_details.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False, indent=2)
    print(f"[SAVE] Details saved to {path}")


def _load_best(phase: str) -> dict | None:
    path = os.path.join(RESULTS_DIR, f"{phase}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        results = json.load(f)
    if not results:
        return None
    # 按 composite 排序取最优
    valid = [r for r in results if "composite" in r and "error" not in r]
    if not valid:
        return None
    return max(valid, key=lambda r: r["composite"])


def _load_results_list(phase: str) -> list[dict]:
    """加载已有结果列表（用于增量保存）"""
    path = os.path.join(RESULTS_DIR, f"{phase}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def print_metrics(result: dict):
    """打印单次实验结果"""
    if "error" in result:
        print(f"  [ERROR] {result['error']}")
        return
    print(f"  总题数: {result['total']}  回答: {result['answered_count']}  拒答: {result['rejected_count']}")
    print(f"  准确率(2分): {result['accuracy_2']:.3f}  平均分: {result['avg_score']:.3f}")
    print(f"  拒答F1: {result['reject_f1']:.3f}  (P={result['reject_precision']:.3f} R={result['reject_recall']:.3f})")
    print(f"  幻觉率: {result['hallucination_rate']:.3f}")
    print(f"  延迟: P50={result['p50_latency_ms']:.0f}ms  P95={result['p95_latency_ms']:.0f}ms")
    print(f"  综合分: {result['composite']:.4f}")
    # 按题型分解
    if "per_category" in result and result["per_category"]:
        cats = result["per_category"]
        parts = [f"  {k}: avg={v['avg_score']:.3f}(n={v['count']})" for k, v in sorted(cats.items())]
        print("  题型分解:")
        for p in parts:
            print(p)


def print_table(results: list[dict], title: str = ""):
    """打印结果排行表"""
    if title:
        print(f"\n[TABLE] {title}")
    print(f"{'Label':<25} {'Acc@2':>6} {'RejF1':>6} {'Halluc':>7} {'P95ms':>7} {'Comp':>7}")
    print("-" * 65)
    for r in results:
        if "error" in r:
            print(f"{r['label']:<25} ERROR: {r['error']}")
            continue
        print(f"{r['label']:<25} {r['accuracy_2']:>6.3f} {r['reject_f1']:>6.3f} "
              f"{r['hallucination_rate']:>7.3f} {r['p95_latency_ms']:>7.0f} {r['composite']:>7.4f}")


# ───────────────────── 主入口 ─────────────────────

async def main():
    parser = argparse.ArgumentParser(description="RAG 参数调优实验框架")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4, 5, 6], help="运行指定 Phase")
    parser.add_argument("--baseline", action="store_true", help="跑基线")
    parser.add_argument("--single", type=str, help="单组参数测试，如 chunk_size=800,overlap=100")
    parser.add_argument("--golden-set", type=str, default="golden_set.json", help="Golden Set 路径")
    parser.add_argument("--upload-dir", type=str, default="./uploads", help="简历文件目录")
    args = parser.parse_args()

    # 加载数据（留出 eval 集：tuning 用于调参，eval 用于 Phase 5 验证）
    print("[LOAD] Loading Golden Set ...")
    golden_set_all = load_golden_set(args.golden_set)
    golden_set = [s for s in golden_set_all if s.get("split") == "tuning"]
    golden_set_eval = [s for s in golden_set_all if s.get("split") == "eval"]
    print(f"   Tuning: {len(golden_set)} QA  |  Eval: {len(golden_set_eval)} QA (held-out)")

    resume_files = sorted(set(qa.get("resume_file", "") for qa in golden_set))
    resume_files = [f for f in resume_files if f]
    if not resume_files:
        print("[FATAL] No resume files found in golden set -- check --upload-dir or dataset")
        sys.exit(1)
    resume_texts = load_resume_texts(resume_files, args.upload_dir)
    if not resume_texts:
        print(f"[FATAL] Could not load any resume files from {args.upload_dir}")
        print(f"  Expected files: {resume_files}")
        sys.exit(1)
    print(f"   共 {len(resume_texts)} 份简历")

    # 保存模型元数据（每次运行自动记录，便于溯源）
    save_model_metadata()

    id_map = _resume_id_map(golden_set)

    if args.baseline:
        await run_baseline(golden_set, id_map, resume_texts)
    elif args.phase == 1:
        await run_phase1(golden_set, id_map, resume_texts)
    elif args.phase == 2:
        await run_phase2(golden_set, id_map, resume_texts)
    elif args.phase == 3:
        await run_phase3(golden_set, id_map, resume_texts)
    elif args.phase == 4:
        await run_phase4(golden_set, id_map, resume_texts)
    elif args.phase == 5:
        # Phase 5：使用 held-out eval 集做最终验证
        print(f"[INFO] Phase 5: using eval set ({len(golden_set_eval)} QA) for final verification")
        await run_phase5(golden_set_eval, id_map, resume_texts)
    elif args.phase == 6:
        await run_phase6(golden_set, id_map, resume_texts)
    elif args.single:
        await run_single(golden_set, id_map, resume_texts, args.single)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
