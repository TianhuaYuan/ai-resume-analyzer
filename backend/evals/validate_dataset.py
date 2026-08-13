"""Validate an evaluation manifest without calling external models."""

from __future__ import annotations

import json
from pathlib import Path


ALLOWED_KINDS = {"resume_parse", "rag_qa", "jd_match", "tool_call", "stream_recovery"}


def validate_manifest(path: str | Path) -> list[str]:
    path = Path(path)
    errors: list[str] = []
    seen: set[str] = set()
    base = path.parent
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: invalid JSON: {exc.msg}")
            continue
        missing = {key for key in ("id", "kind", "input", "expected", "tags") if key not in item}
        if missing:
            errors.append(f"line {line_no}: missing {sorted(missing)}")
            continue
        sample_id = item["id"]
        if not isinstance(sample_id, str) or not sample_id.strip():
            errors.append(f"line {line_no}: id must be non-empty string")
        elif sample_id in seen:
            errors.append(f"line {line_no}: duplicate id {sample_id}")
        seen.add(sample_id)
        if item["kind"] not in ALLOWED_KINDS:
            errors.append(f"line {line_no}: unsupported kind {item['kind']}")
        for field in ("input", "expected"):
            target = base / str(item[field])
            if not target.is_file():
                errors.append(f"line {line_no}: missing {field} file {item[field]}")
        if not isinstance(item["tags"], list) or not item["tags"]:
            errors.append(f"line {line_no}: tags must be non-empty list")
    return errors


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    errors = validate_manifest(args.manifest)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"valid evaluation manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
