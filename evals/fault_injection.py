"""Deterministic fault-injection contract runner.

The harness is provider-independent: it emits expected acceptance records so a
real integration adapter can attach raw logs without changing the matrix.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", default="evals/fault_matrix.json")
    p.add_argument("--out", required=True)
    p.add_argument("--mode", choices=["dry-run", "live"], default="dry-run")
    args = p.parse_args()
    matrix = json.loads(Path(args.matrix).read_text(encoding="utf-8"))
    rows = []
    for item in matrix["faults"]:
        rows.append({"fault_id": item["id"], "expected": item["expected"],
                     "mode": args.mode, "status": "not_executed" if args.mode == "dry-run" else "pending_adapter",
                     "raw_log": None, "verified": False})
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "rows": rows,
               "warning": "dry-run is a contract preview; it is not production evidence"}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"faults": len(rows), "mode": args.mode, "verified": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
