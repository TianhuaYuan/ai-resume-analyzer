from __future__ import annotations

from typing import Any

REQUIRED = {
    "case_id", "category", "task_type", "input", "expected", "scorer",
    "risk", "provenance", "license", "version"
}
ALLOWED_CATEGORIES = {"standard", "boundary", "adversarial"}


def validate_case(case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(f"missing:{key}" for key in sorted(REQUIRED - case.keys()))
    if case.get("category") not in ALLOWED_CATEGORIES:
        errors.append("invalid:category")
    if not isinstance(case.get("case_id"), str) or not case.get("case_id"):
        errors.append("invalid:case_id")
    if not isinstance(case.get("input"), dict) or not case.get("input"):
        errors.append("invalid:input")
    if not isinstance(case.get("expected"), dict):
        errors.append("invalid:expected")
    scorer = case.get("scorer")
    if not isinstance(scorer, list) or not scorer:
        errors.append("invalid:scorer")
    if case.get("license") != "project-synthetic-v1":
        errors.append("invalid:license")
    return errors
