from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from schema import validate_case

DATA = Path(__file__).resolve().parent / "datasets" / "cases.jsonl"


def main() -> None:
    if not DATA.exists():
        raise SystemExit("dataset missing; run generate_dataset.py")
    cases = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = [(c.get("case_id"), validate_case(c)) for c in cases if validate_case(c)]
    ids = [c.get("case_id") for c in cases]
    counts = Counter(c.get("category") for c in cases)
    deep = sum(bool(c.get("deep_research")) for c in cases)
    if errors or len(cases) != 96 or len(set(ids)) != len(ids) or counts != Counter({"standard": 48, "boundary": 24, "adversarial": 24}) or deep < 15:
        raise SystemExit(json.dumps({"errors": errors, "counts": counts, "deep_research": deep}, ensure_ascii=False))
    print(json.dumps({"valid": True, "cases": len(cases), "counts": counts, "deep_research": deep, "sha256": hashlib.sha256(DATA.read_bytes()).hexdigest()}, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
