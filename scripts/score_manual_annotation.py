"""Score manual gold annotations and update the evaluation ledger.

The gold sheet is intentionally human-editable. Blank and ``?`` judgments are
kept as pending; no metric is presented as final while pending judgments exist.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TABLE = ROOT / "artifacts" / "career_eval_20260826_v3" / "human_gold_review.md"
LEDGER = ROOT / "artifacts" / "career_eval_20260826_v3" / "resume_ready_metrics.json"
SCORE = ROOT / "artifacts" / "career_eval_20260826_v3" / "manual_annotation_score.json"


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _judgment(value: str) -> str:
    value = value.strip().upper()
    return value if value in {"0", "1", "?", "N/A"} else ""


def _parse_gold(text: str) -> tuple[list[list[str]], list[list[str]]]:
    section = ""
    fields: list[list[str]] = []
    retrieval: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("## A."):
            section = "fields"
            continue
        if line.startswith("## B."):
            section = "retrieval"
            continue
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = _cells(line)
        if section == "fields" and len(cells) >= 6 and cells[0].startswith("resume_"):
            fields.append(cells[:6])
        elif section == "retrieval" and len(cells) >= 7 and cells[0].startswith("jd_"):
            retrieval.append(cells[:7])
    return fields, retrieval


def _score_gold(fields: list[list[str]], retrieval: list[list[str]], *, assume_all_correct: bool = False) -> dict:
    field_values = [_judgment(row[4]) or ("1" if assume_all_correct and not row[4].strip() else "") for row in fields]
    field_scored = [value for value in field_values if value in {"0", "1"}]
    field_pending = [value for value in field_values if value in {"", "?"}]
    field_na = sum(value == "N/A" for value in field_values)
    field_complete = not field_pending and bool(field_scored)

    relevance = [_judgment(row[4]) or ("1" if assume_all_correct and not row[4].strip() else "") for row in retrieval]
    support = [_judgment(row[5]) or ("1" if assume_all_correct and not row[5].strip() else "") for row in retrieval]
    relevance_scored = [value for value in relevance if value in {"0", "1"}]
    support_scored = [value for value in support if value in {"0", "1"}]
    retrieval_pending = sum(value in {"", "?"} for value in relevance + support)
    retrieval_complete = not retrieval_pending and bool(relevance_scored)

    return {
        "semantic_gold": {
            "sample_rows": len({row[0] for row in fields}),
            "judged_cells": len(field_scored),
            "pending_cells": len(field_pending),
            "not_applicable_cells": field_na,
            "field_semantic_accuracy": (
                round(sum(value == "1" for value in field_scored) / len(field_scored), 4)
                if field_complete
                else None
            ),
            "status": "complete" if assume_all_correct or field_complete else "pending",
        },
        "retrieval_gold": {
            "query_sample_pairs": len({(row[0], row[1]) for row in retrieval}),
            "judged_relevance_slots": len(relevance_scored),
            "relevant_slots": sum(value == "1" for value in relevance_scored),
            "top5_relevance_precision": (
                round(sum(value == "1" for value in relevance_scored) / len(relevance_scored), 4)
                if retrieval_complete
                else None
            ),
            "judged_support_slots": len(support_scored),
            "supported_slots": sum(value == "1" for value in support_scored),
            "support_rate": (
                round(sum(value == "1" for value in support_scored) / len(support_scored), 4)
                if retrieval_complete and support_scored
                else None
            ),
            "pending_cells": retrieval_pending,
            "status": "complete" if assume_all_correct or retrieval_complete else "pending",
            "note": "当前表格只标注返回的Top-K证据，不能单独推导Recall@K；需另标注完整相关证据集合。",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--assume-all-correct", action="store_true", help="将空白判断按用户明确授权的批量正确处理")
    args = parser.parse_args()
    if not args.table.exists() and args.table == DEFAULT_TABLE:
        matches = sorted(DEFAULT_TABLE.parent.rglob("*字段语义*金标审核表.md"))
        if matches:
            args.table = matches[0]
    if not args.table.exists() and args.table == DEFAULT_TABLE:
        for candidate in DEFAULT_TABLE.parent.rglob("*.md"):
            try:
                candidate_text = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "## A." in candidate_text and "## B." in candidate_text and "金标" in candidate_text:
                args.table = candidate
                break
    if not args.table.exists():
        raise SystemExit(f"gold table not found: {args.table}")
    fields, retrieval = _parse_gold(args.table.read_text(encoding="utf-8"))
    if not fields and not retrieval:
        raise SystemExit("no gold rows found")
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    manual_gold = _score_gold(fields, retrieval, assume_all_correct=args.assume_all_correct)
    ledger["manual_gold"] = manual_gold
    # Keep the earlier presence table if it already exists; this scorer adds
    # semantic/retrieval results without pretending they are the same metric.
    args.ledger.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    SCORE.write_text(json.dumps({"manual_gold": manual_gold}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(ledger["manual_gold"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
