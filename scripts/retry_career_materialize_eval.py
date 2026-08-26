"""Retry lazy upload->builder materialization on the isolated evaluation set."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx


async def run(args: argparse.Namespace) -> None:
    output_dir = args.output_dir.resolve()
    credentials = json.loads((output_dir / "runtime_credentials.local.json").read_text(encoding="utf-8"))
    all_results = json.loads((output_dir / "upload_results.json").read_text(encoding="utf-8"))
    results = all_results
    if args.sample_ids:
        wanted = set(args.sample_ids)
        results = [row for row in results if row.get("sample_id") in wanted]
    by_user = {int(account["user_id"]): account for account in credentials}
    async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout_seconds, read=args.timeout_seconds)) as client:
        semaphore = asyncio.Semaphore(args.concurrency)

        async def one(row: dict[str, Any]) -> dict[str, Any]:
            account = by_user[int(row["user_id"])]
            async with semaphore:
                response = await client.get(
                    f"{args.base_url}/api/v1/resumes/{row['resume_id']}/builder",
                    headers={"Authorization": f"Bearer {account['access_token']}"},
                )
                try:
                    body = response.json()
                except Exception:
                    body = response.text[:2000]
                return {
                    "sample_id": row["sample_id"],
                    "resume_id": row["resume_id"],
                    "user_id": row["user_id"],
                    "http_status": response.status_code,
                    "modules_materialized": body.get("modules_materialized") if isinstance(body, dict) else None,
                    "module_count": len(body.get("modules", [])) if isinstance(body, dict) else 0,
                    "body": body,
                }

        materialized = await asyncio.gather(*(one(row) for row in results if row.get("final_status") == "ready"))
    (output_dir / "materialize_results.json").write_text(json.dumps(materialized, ensure_ascii=False, indent=2), encoding="utf-8")
    result_by_id = {item["sample_id"]: item for item in materialized}
    for row in all_results:
        retry = result_by_id.get(row["sample_id"])
        if retry:
            row["materialize_http_status"] = retry["http_status"]
            row["materialize_modules"] = retry["module_count"]
            row["materialize_success"] = retry["modules_materialized"] is True and retry["module_count"] > 0
            row["builder_response_retry"] = retry["body"]
    (output_dir / "upload_results.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "sample_count": len(materialized),
        "materialized_count": sum(bool(item["modules_materialized"]) and item["module_count"] > 0 for item in materialized),
        "failed_count": sum(not (bool(item["modules_materialized"]) and item["module_count"] > 0) for item in materialized),
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8082")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts") / "career_eval_20260826")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--sample-ids", nargs="*", help="Only retry selected sample IDs")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
