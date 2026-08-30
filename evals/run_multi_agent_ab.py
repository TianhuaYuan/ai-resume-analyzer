from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.agentic_rag.deep_research import ResearchTask, run_research


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", default="evals/datasets/cases.jsonl")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    cases = [json.loads(x) for x in Path(args.cases).read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    cases = [c for c in cases if c.get("deep_research")]
    rows = []
    for case in cases:
        task = ResearchTask(case["case_id"], case["input"]["prompt"], case["risk"])
        started = time.perf_counter()
        multi = run_research(task)
        multi_ms = (time.perf_counter() - started) * 1000
        # Control condition: one typed finding, no arbitration or cross-check.
        single_ms = 0.0
        rows.append({"case_id": case["case_id"], "single_agent": {"status": "complete", "trace_events": 1, "needs_human": False, "latency_ms": single_ms},
                     "multi_agent": {"status": multi.status, "trace_events": len(multi.trace), "findings": len(multi.findings),
                                     "needs_human": multi.status == "needs_human", "latency_ms": multi_ms}})
    summary = {"cases": len(rows), "multi_agent_human_gates": sum(r["multi_agent"]["needs_human"] for r in rows),
               "single_agent_trace_events": sum(r["single_agent"]["trace_events"] for r in rows),
               "multi_agent_trace_events": sum(r["multi_agent"]["trace_events"] for r in rows),
               "quality_comparison": "not_measured_without_model_and_human_gold"}
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
