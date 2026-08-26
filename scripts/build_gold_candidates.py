"""Build conservative, non-final candidates for the human gold sheet.

Only exact substring matches for basic fields are proposed. Module existence is
reported separately and is never treated as semantic correctness.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "career_eval_20260826_v3"
OUTPUT = ARTIFACT / "manual_gold_candidates.json"


def main() -> None:
    uploads = json.loads((ARTIFACT / "upload_results.json").read_text(encoding="utf-8"))
    candidates = []
    for item in uploads:
        sample = str(item.get("sample_id", ""))
        pdf = ARTIFACT / "samples" / f"{sample}.pdf"
        if not pdf.exists():
            continue
        with fitz.open(pdf) as doc:
            source = "\n".join(page.get_text() for page in doc)
        modules = {
            str(m.get("module_type")): m.get("content", {})
            for m in (item.get("builder_response", {}) or {}).get("modules", [])
            if isinstance(m, dict)
        }
        basic = modules.get("basic_info", {})
        exact = {}
        for field in ("name", "email", "phone"):
            value = str(basic.get(field) or "").strip()
            exact[field] = {
                "candidate": "1" if value and value.lower() in source.lower() else "?",
                "model_value_present": bool(value),
                "exact_source_match": bool(value and value.lower() in source.lower()),
            }
        candidates.append({
            "sample_id": sample,
            "exact_basic_info_candidates": exact,
            "module_presence_only": {name: name in modules for name in ("education", "work_experience", "project_experience", "skills")},
            "note": "候选仅表示逐字命中原文；1 仍需人工确认语义、边界和归属。",
        })
    OUTPUT.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
