"""Compare resume extraction with thinking disabled/enabled on identical inputs."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import fitz

from services.resume_parser import parse_text_to_modules


def read_pdf(path: Path) -> str:
    with fitz.open(path) as document:
        return "\n".join(page.get_text("text") for page in document)


async def one(path: Path, mode: bool, user_id: int | None) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        modules = await parse_text_to_modules(
            read_pdf(path), user_id=user_id, thinking_enabled=mode, source_filename=path.name
        )
        return {
            "sample": path.stem,
            "thinking_enabled": mode,
            "ok": True,
            "module_count": len(modules),
            "module_types": [getattr(m, "module_type", None) for m in modules],
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    except Exception as exc:  # record outcome without exposing provider details
        return {
            "sample": path.stem,
            "thinking_enabled": mode,
            "ok": False,
            "error_type": type(exc).__name__,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }


async def main(args: argparse.Namespace) -> None:
    sample_dir = args.sample_dir.resolve()
    names = args.samples or ["resume_01.pdf", "resume_11.pdf", "resume_20.pdf"]
    paths = [sample_dir / name for name in names]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise SystemExit(f"missing samples: {missing}")
    results: list[dict[str, Any]] = []
    for path in paths:
        for mode in (False, True):
            results.append(await one(path, mode, args.user_id))
    output = {
        "generated_at": time.time(),
        "samples": names,
        "same_input_pairs": True,
        "results": results,
        "quality_semantic_score": None,
        "note": "没有人工字段金标；结果只比较解析链路成功率、模块数量、时延和可观测 token（如 provider 返回）。",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"runs": len(results), "ok": sum(x["ok"] for x in results)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--samples", nargs="*")
    asyncio.run(main(parser.parse_args()))
