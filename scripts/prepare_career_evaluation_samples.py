"""Create reproducible, non-destructive PDF samples for career evaluation.

The source PDFs in D:\\Edge are compilation documents: a page can contain the
end of one resume and the beginning of the next. This script detects "简历 N"
markers, crops each logical range into a separate PDF, and writes a manifest
with every source offset. Source files are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz


# Names often follow the number without a separating space, so only reject a
# following digit (to keep "简历 1" distinct from "简历 10").
MARKER = re.compile(r"简历\s*(\d{1,2})(?!\d)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def page_markers(document: fitz.Document, source_name: str) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for page_no, page in enumerate(document):
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line["spans"])
                match = MARKER.search(text)
                if match:
                    markers.append(
                        {
                            "resume_number": int(match.group(1)),
                            "source_pdf": source_name,
                            "page": page_no + 1,
                            "y": round(float(line["bbox"][1]), 3),
                            "marker_text": text.strip(),
                        }
                    )
    return markers


def sample_text(document: fitz.Document, start: dict[str, Any], end: dict[str, Any] | None) -> str:
    start_index = start["page"] - 1
    end_index = (end["page"] - 1) if end else len(document) - 1
    pieces: list[str] = []
    for page_index in range(start_index, end_index + 1):
        page = document[page_index]
        top = start["y"] if page_index == start_index else 0
        bottom = end["y"] if end and page_index == end_index else page.rect.height
        if bottom > top:
            pieces.append(page.get_text("text", clip=fitz.Rect(0, top, page.rect.width, bottom)))
    return "\n".join(pieces).strip()


def write_cropped_pdf(
    document: fitz.Document,
    start: dict[str, Any],
    end: dict[str, Any] | None,
    target: Path,
) -> None:
    start_index = start["page"] - 1
    end_index = (end["page"] - 1) if end else len(document) - 1
    output = fitz.open()
    for page_index in range(start_index, end_index + 1):
        page = document[page_index]
        top = start["y"] if page_index == start_index else 0
        bottom = end["y"] if end and page_index == end_index else page.rect.height
        if bottom <= top:
            continue
        clip = fitz.Rect(0, top, page.rect.width, bottom)
        out_page = output.new_page(width=clip.width, height=clip.height)
        out_page.show_pdf_page(out_page.rect, document, page_index, clip=clip)
    if output.page_count == 0:
        raise ValueError(f"No printable content for resume {start['resume_number']}")
    output.save(target, garbage=4, deflate=True)
    output.close()


def parse_jds(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        clean = line.strip()
        if clean.startswith("#"):
            match = re.search(r"(?:JD|岗位)\s*(\d{1,2})", clean, flags=re.IGNORECASE)
            if match:
                entries.append({"jd_number": int(match.group(1)), "line": index, "heading": clean.lstrip("# ")})
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts") / "career_eval_20260826",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    samples_dir = output_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    # This directory is generated exclusively by this script. Clearing only
    # prior generated PDFs prevents stale samples after marker-rule changes.
    for old_sample in samples_dir.glob("resume_*.pdf"):
        old_sample.unlink()

    pdfs = sorted(args.source_dir.glob("*.pdf"), key=lambda p: p.name)
    if len(pdfs) != 2:
        raise RuntimeError(f"Expected exactly two source PDFs, found {len(pdfs)}")
    jd_path = args.source_dir / "1-10JD.md"
    if not jd_path.exists():
        raise RuntimeError(f"Missing JD file: {jd_path}")

    grouped: list[tuple[Path, fitz.Document, list[dict[str, Any]]]] = []
    for pdf_path in pdfs:
        document = fitz.open(pdf_path)
        grouped.append((pdf_path, document, page_markers(document, pdf_path.name)))

    all_samples: list[dict[str, Any]] = []
    for pdf_path, document, markers in grouped:
        for marker_index, start in enumerate(markers):
            end = markers[marker_index + 1] if marker_index + 1 < len(markers) else None
            text = sample_text(document, start, end)
            number = start["resume_number"]
            # Resume 6 is explicitly a duplicate placeholder in supplied data.
            duplicate = number == 6 and "重复" in text and len(text) < 100
            item: dict[str, Any] = {
                "sample_id": f"resume_{number:02d}",
                "resume_number": number,
                "source_pdf": pdf_path.name,
                "source_sha256": sha256(pdf_path),
                "start": {"page": start["page"], "y": start["y"], "marker": start["marker_text"]},
                "end_before": ({"page": end["page"], "y": end["y"], "marker": end["marker_text"]} if end else None),
                "extracted_characters": len(text),
                "status": "duplicate_skipped" if duplicate else "ready_for_evaluation",
                "duplicate_of": "resume_02" if duplicate else None,
            }
            if not duplicate:
                target = samples_dir / f"{item['sample_id']}.pdf"
                write_cropped_pdf(document, start, end, target)
                item["split_pdf"] = str(target.relative_to(output_dir).as_posix())
                item["split_pdf_sha256"] = sha256(target)
            all_samples.append(item)

    for _, document, _ in grouped:
        document.close()

    all_samples.sort(key=lambda value: value["resume_number"])
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(args.source_dir),
        "valid_sample_count": sum(item["status"] == "ready_for_evaluation" for item in all_samples),
        "excluded_sample_count": sum(item["status"] != "ready_for_evaluation" for item in all_samples),
        "important_limitations": [
            "Supplied PDFs are compilation documents; samples are cropped at visible resume markers.",
            "Resume 06 is an explicit duplicate placeholder of resume 02 and is excluded from quality denominators.",
            "No source PDF contains an embedded avatar; avatar upload/export requires a separate synthetic image fixture.",
        ],
        "samples": all_samples,
        "jd_source": {"path": str(jd_path), "sha256": sha256(jd_path), "entries": parse_jds(jd_path)},
    }
    (output_dir / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output_dir": str(output_dir), "valid": manifest["valid_sample_count"], "excluded": manifest["excluded_sample_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
