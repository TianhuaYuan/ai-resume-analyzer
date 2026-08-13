"""Compare resume extraction with thinking disabled/enabled on one stored resume.

This is a read-only evaluation: it never writes parsed modules back to the resume.
Only aggregate coverage/timing metrics are printed so personal resume text does not
leak into logs or reports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from core.database import AsyncSessionLocal, engine
from models.resume import Resume
from services.resume_parser import parse_text_to_modules


def _walk(value: Any) -> tuple[int, int]:
    """Return (non-empty scalar count, URL count) without exposing values."""
    if isinstance(value, dict):
        totals = [_walk(item) for item in value.values()]
    elif isinstance(value, list):
        totals = [_walk(item) for item in value]
    elif value not in (None, "", [], {}):
        text = str(value)
        return 1, int(text.startswith(("http://", "https://")))
    else:
        return 0, 0
    return sum(item[0] for item in totals), sum(item[1] for item in totals)


async def _evaluate(resume_id: int, thinking: bool) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        resume = await db.get(Resume, resume_id)
        if resume is None or not resume.parsed_text:
            raise SystemExit(f"resume {resume_id} has no parsed text")
        source_chars = len(resume.parsed_text)
        started = time.perf_counter()
        try:
            modules = await parse_text_to_modules(
                resume.parsed_text,
                thinking_enabled=thinking,
                source_filename=resume.filename,
            )
        except Exception as exc:  # evaluation must report failures, not hide them
            return {
                "thinking": thinking,
                "ok": False,
                "elapsed_seconds": round(time.perf_counter() - started, 2),
                "source_chars": source_chars,
                "error_type": type(exc).__name__,
            }

    scalar_count = 0
    url_count = 0
    item_count = 0
    module_types: list[str] = []
    for module in modules:
        module_types.append(module.module_type.value)
        content = module.content
        scalar_delta, url_delta = _walk(content)
        scalar_count += scalar_delta
        url_count += url_delta
        if isinstance(content, dict) and isinstance(content.get("items"), list):
            item_count += len(content["items"])

    return {
        "thinking": thinking,
        "ok": True,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "source_chars": source_chars,
        "module_count": len(modules),
        "module_types": module_types,
        "item_count": item_count,
        "non_empty_scalar_count": scalar_count,
        "url_count": url_count,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("resume_id", type=int)
    parser.add_argument(
        "--mode",
        choices=("disabled", "enabled", "both"),
        default="both",
    )
    args = parser.parse_args()
    results = []
    modes = {
        "disabled": (False,),
        "enabled": (True,),
        "both": (False, True),
    }[args.mode]
    for thinking in modes:
        results.append(await _evaluate(args.resume_id, thinking))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
