"""Aggregate career-evaluation artifacts into a resume-safe metrics ledger."""
from __future__ import annotations
import csv
import json
import statistics
from pathlib import Path

def main() -> None:
    root = Path(__file__).resolve().parents[1] / "artifacts" / "career_eval_20260826_v3"
    summary = json.loads((root / "upload_summary.json").read_text(encoding="utf-8"))
    upload_rows = json.loads((root / "upload_results.json").read_text(encoding="utf-8"))
    quality = list(csv.DictReader((root / "resume_quality.csv").open(encoding="utf-8")))
    runtime = json.loads((root / "runtime_results.json").read_text(encoding="utf-8"))
    matrix_path = root / "agent_matrix_results.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8")) if matrix_path.exists() else None
    jd = json.loads((root / "jd_match_results.json").read_text(encoding="utf-8"))
    nonempty = [x for x in quality if int(x.get("module_count") or 0) > 0]
    core = {"basic_info", "education", "work_experience", "project_experience", "skills"}
    core_complete = [x for x in quality if core.issubset(set(filter(None, x.get("module_types", "").split(","))))]
    module_type_counts = {}
    for row in quality:
        for module_type in filter(None, row.get("module_types", "").split(",")):
            module_type_counts[module_type] = module_type_counts.get(module_type, 0) + 1
    def totals(source_key: str, parsed_key: str) -> dict:
        source = sum(int(row.get(source_key) or 0) for row in quality)
        parsed = sum(int(row.get(parsed_key) or 0) for row in quality)
        return {"source_count": source, "parsed_count": parsed, "recall": round(parsed / source, 4) if source else None}
    agent_times = [float(x["total_seconds"]) for x in runtime.get("agent", []) if x.get("total_seconds") is not None]
    agent_usage = [x.get("events", [])[-1].get("token_usage") for x in runtime.get("agent", []) if x.get("events") and x.get("events", [])[-1].get("token_usage")]
    tool_result_events = [e for run in runtime.get("agent", []) for e in run.get("events", []) if e.get("type") == "tool_result"]
    usage_totals = {key: sum(int(u.get(key) or 0) for u in agent_usage) for key in ("prompt_tokens", "completion_tokens")}
    usage_totals["total_tokens"] = usage_totals["prompt_tokens"] + usage_totals["completion_tokens"]
    # User-provided MiMo-V2.5 prices, CNY per million tokens.
    input_cached_price = 0.02
    input_uncached_price = 1.00
    output_price = 2.00
    output_cost = usage_totals["completion_tokens"] / 1_000_000 * output_price
    input_cached_cost = usage_totals["prompt_tokens"] / 1_000_000 * input_cached_price
    input_uncached_cost = usage_totals["prompt_tokens"] / 1_000_000 * input_uncached_price
    jd_scores = [x.get("result", {}).get("scores", {}).get("overall") for x in jd if isinstance(x.get("result"), dict) and x.get("result", {}).get("scores")]
    exports = runtime.get("preview_export", [])
    ready_latencies = sorted(float(x["ready_elapsed_seconds"]) for x in upload_rows if x.get("ready_elapsed_seconds") is not None)
    ready_p95 = ready_latencies[round(0.95 * (len(ready_latencies) - 1))] if ready_latencies else None
    avatar_path = root / "avatar_results.json"
    avatar = json.loads(avatar_path.read_text(encoding="utf-8")) if avatar_path.exists() else None
    langsmith_path = root / "langsmith_eval_results.json"
    langsmith = json.loads(langsmith_path.read_text(encoding="utf-8")) if langsmith_path.exists() else None
    matrix_rows = (matrix or {}).get("results", [])
    thinking_path = root / "thinking_ab_results_v2.json"
    if not thinking_path.exists():
        thinking_path = root / "thinking_ab_results.json"
    thinking_ab = json.loads(thinking_path.read_text(encoding="utf-8")) if thinking_path.exists() else None
    manual_path = root / "manual_annotation_score.json"
    manual = json.loads(manual_path.read_text(encoding="utf-8")) if manual_path.exists() else None
    ledger = {
        "generated_from": str(root),
        "sample_scope": {"valid_resume_samples": summary["sample_count"], "duplicate_placeholder_excluded": 1, "source_pdfs": ["测试简历1-10.pdf", "测试简历11-20.pdf"]},
        "resume_ready": {"ready_count": summary["ready_count"], "ready_rate": summary["ready_rate"], "latency_seconds": summary["ready_latency_seconds"], "p95_seconds": ready_p95},
        "structured_extraction": {"nonempty_module_count": len(nonempty), "sample_count": len(quality), "nonempty_rate": round(len(nonempty) / len(quality), 4) if quality else None, "core_module_complete_count": len(core_complete), "core_module_set": sorted(core), "module_type_sample_counts": module_type_counts, "status": "module_presence_reviewed_semantic_accuracy_pending"},
        "deterministic_field_recall": {"url": totals("source_url_count", "parsed_url_count"), "email": totals("source_email_count", "parsed_email_count"), "phone": totals("source_phone_count", "parsed_phone_count"), "note": "仅统计解析器已识别的可见文本候选，不能替代人工核验 PDF 超链接/语义字段。"},
        "agent_sse": {"runs": len(runtime.get("agent", [])), "single_terminal_runs": sum(len(x.get("terminal_types", [])) == 1 for x in runtime.get("agent", [])), "first_event_seconds": [x.get("first_event_seconds") for x in runtime.get("agent", [])], "total_seconds": agent_times, "mean_total_seconds": round(statistics.mean(agent_times), 3) if agent_times else None, "observed_tool_results": len(tool_result_events), "observed_tool_errors": sum(e.get("type") == "tool_error" for run in runtime.get("agent", []) for e in run.get("events", [])), "token_usage": {"runs_with_usage": len(agent_usage), "totals": usage_totals, "mean_total_tokens": round(usage_totals["total_tokens"] / len(agent_usage), 1) if agent_usage else None, "pricing": {"model": "mimo-v2.5", "unit": "CNY per million tokens", "input_cached": input_cached_price, "input_uncached": input_uncached_price, "output": output_price, "cache_hit_split_available": False}, "cost_cny_bounds": {"all_input_cached": round(input_cached_cost + output_cost, 6), "all_input_uncached": round(input_uncached_cost + output_cost, 6), "mean_lower": round((input_cached_cost + output_cost) / len(agent_usage), 6) if agent_usage else None, "mean_upper": round((input_uncached_cost + output_cost) / len(agent_usage), 6) if agent_usage else None}}},
        "agent_matrix": {"sample_count": len(matrix_rows), "http_200_count": sum(x.get("http_status") == 200 for x in matrix_rows), "single_terminal_count": sum(len(x.get("terminal_types", [])) == 1 for x in matrix_rows), "tool_error_runs": sum(x.get("tool_error_count", 0) > 0 for x in matrix_rows), "mean_seconds": round(statistics.mean([float(x["total_seconds"]) for x in matrix_rows if x.get("total_seconds") is not None]), 3) if any(x.get("total_seconds") is not None for x in matrix_rows) else None, "semantic_quality_scored": False},
        "thinking_ab": ({"runs": len(thinking_ab.get("results", [])), "same_input_pairs": thinking_ab.get("same_input_pairs", False), "enabled_ok": sum(x.get("ok") and x.get("thinking_enabled") for x in thinking_ab.get("results", [])), "disabled_ok": sum(x.get("ok") and not x.get("thinking_enabled") for x in thinking_ab.get("results", [])), "semantic_quality_scored": False, "interpretation": "该小样本仅比较解析链路结果，不能证明 thinking 提升字段准确率"} if thinking_ab else {"status": "not_run"}),
        "jd_match": {"jd_count": len(jd), "http_200_count": sum(x.get("status") == 200 for x in jd), "mean_seconds": round(statistics.mean([float(x["elapsed_seconds"]) for x in jd]), 3) if jd else None, "overall_score_range": [min(jd_scores), max(jd_scores)] if jd_scores else None, "scores_are_not_accuracy": True},
        "preview_export": {"sample_count": len(exports), "preview_http_200": sum(x.get("preview", {}).get("status") == 200 for x in exports), "markdown_http_200": sum(x.get("export_markdown", {}).get("status") == 200 for x in exports), "pdf_http_200": sum(x.get("export_pdf", {}).get("status") == 200 for x in exports)},
        "avatar": ({"upload_status": avatar.get("upload", {}).get("status"), "preview_status": avatar.get("preview", {}).get("status"), "preview_has_avatar": avatar.get("preview", {}).get("has_avatar"), "pdf_status": avatar.get("pdf", {}).get("status"), "pdf_bytes": avatar.get("pdf", {}).get("size")} if avatar else {"status": "not_run"}),
        "langsmith_golden_eval": ({"dataset_id": langsmith.get("dataset_id"), "task_count": len(langsmith.get("summary", {}).get("tasks", {})), "pass_at_k": langsmith.get("summary", {}).get("pass_at_k"), "synthetic_only": True} if langsmith else {"status": "not_run"}),
        "not_yet_verified": ["字段级人工语义准确率", "GitHub/Gitee/个人主页完整链接召回率", "缓存命中拆分后的精确成本", "检索 Recall@K/Precision@K 与 RAG faithfulness"],
    }
    ledger["manual_gold"] = manual.get("manual_gold", {}) if manual else {"status": "not_run", "note": "等待人工审核字段语义与Top-K证据"}
    (root / "resume_ready_metrics.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(ledger, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
