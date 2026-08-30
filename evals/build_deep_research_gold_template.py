from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    cases = [json.loads(x) for x in (root / "datasets/cases.jsonl").read_text(encoding="utf-8").splitlines()]
    selected = [c for c in cases if c.get("deep_research")][:15]
    rows = []
    for c in selected:
        rows.append({"case_id": c["case_id"], "evidence_supported": None, "conflict_resolution": None,
                     "unsafe_should_refuse": None, "citation_correct": None, "reviewer_notes": "",
                     "reviewer_id": "", "reviewed_at": ""})
    out = root / "datasets/deep_research_gold_template.json"
    out.write_text(json.dumps({"version": "1.0", "status": "pending_human_review", "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
