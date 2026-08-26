"""Run isolated real upload/parse evaluation and emit resume-ready metrics.

Only consumes generated samples under artifacts/career_eval_20260826. It does
not read personal resume files and does not mutate source PDFs.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
import httpx


URL_RE = re.compile(r"https?://[^\s<>\"')\]}]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def normalize_url(value: str) -> str:
    return value.rstrip(".,;:!?）)]}").lower()


def flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{flatten(k)} {flatten(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " ".join(flatten(item) for item in value)
    return str(value or "")


def source_text(pdf_path: Path) -> str:
    document = fitz.open(pdf_path)
    try:
        return "\n".join(page.get_text("text") for page in document)
    finally:
        document.close()


async def api_json(client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
    # Parsing/materialization can legitimately outlive the short polling interval.
    # Keep the evaluation client from converting a slow but healthy parse into a
    # transport failure; the outer upload timeout remains the overall deadline.
    kwargs.setdefault("timeout", httpx.Timeout(180.0, connect=20.0))
    response = await client.request(method, url, **kwargs)
    try:
        body: Any = response.json()
    except Exception:
        body = response.text[:2000]
    return response.status_code, body


async def create_account(client: httpx.AsyncClient, base_url: str, ordinal: int, stamp: str) -> dict[str, Any]:
    password = f"EvalAgent{stamp[-6:]}{ordinal}"
    email = f"eval.{stamp}.u{ordinal}@gmail.com"
    username = f"eval{stamp[-6:]}u{ordinal}"
    headers = {"Origin": "http://127.0.0.1:5173"}
    status, body = await api_json(
        client,
        "POST",
        f"{base_url}/api/v1/auth/register",
        headers=headers,
        json={
            "username": username,
            "email": email,
            "password": password,
            "password_confirm": password,
            "verification_code": "000000",
            "source": "career-evaluation",
        },
    )
    if status not in (200, 201):
        raise RuntimeError(f"register failed: {status} {body}")
    status, login = await api_json(
        client,
        "POST",
        f"{base_url}/api/v1/auth/login",
        headers=headers,
        json={"email": email, "password": password},
    )
    if status != 200 or not isinstance(login, dict) or not login.get("access_token"):
        raise RuntimeError(f"login failed: {status} {login}")
    return {
        "ordinal": ordinal,
        "user_id": body.get("id"),
        "email": email,
        "password": password,
        "access_token": login["access_token"],
    }


async def upload_and_poll(
    client: httpx.AsyncClient,
    base_url: str,
    account: dict[str, Any],
    sample: dict[str, Any],
    output_dir: Path,
    poll_interval: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    sample_id = sample["sample_id"]
    pdf_path = (output_dir / sample["split_pdf"]).resolve()
    headers = {
        "Authorization": f"Bearer {account['access_token']}",
        "Idempotency-Key": f"career-eval-{account['user_id']}-{sample_id}",
    }
    started = time.perf_counter()
    status, upload = await api_json(
        client,
        "POST",
        f"{base_url}/api/v1/resumes",
        headers=headers,
        files={"file": (pdf_path.name, pdf_path.read_bytes(), "application/pdf")},
    )
    result: dict[str, Any] = {
        "sample_id": sample_id,
        "resume_number": sample["resume_number"],
        "account_ordinal": account["ordinal"],
        "user_id": account["user_id"],
        "source_pdf": sample["source_pdf"],
        "split_pdf": sample["split_pdf"],
        "upload_http_status": status,
        "upload_response": upload,
        "upload_elapsed_seconds": round(time.perf_counter() - started, 3),
        "status_timeline": [],
    }
    if status not in (200, 202) or not isinstance(upload, dict) or not upload.get("id"):
        result["final_status"] = "upload_failed"
        result["error"] = upload
        return result
    resume_id = int(upload["id"])
    result["resume_id"] = resume_id
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        status, body = await api_json(
            client,
            "GET",
            f"{base_url}/api/v1/resumes/{resume_id}",
            headers={"Authorization": f"Bearer {account['access_token']}"},
        )
        now = time.perf_counter()
        timeline_item = {
            "elapsed_seconds": round(now - started, 3),
            "http_status": status,
            "status": body.get("status") if isinstance(body, dict) else None,
            "status_message": body.get("status_message") if isinstance(body, dict) else None,
            "parse_progress": body.get("parse_progress") if isinstance(body, dict) else None,
            "is_indexed": body.get("is_indexed") if isinstance(body, dict) else None,
        }
        result["status_timeline"].append(timeline_item)
        if status != 200 or not isinstance(body, dict):
            result["final_status"] = "poll_failed"
            result["error"] = body
            break
        current = body.get("status")
        if current in {"ready", "failed", "error"}:
            result["final_status"] = current
            result["ready_elapsed_seconds"] = round(now - started, 3) if current == "ready" else None
            result["resume_response"] = body
            if current == "ready":
                builder_status, builder = await api_json(
                    client,
                    "GET",
                    f"{base_url}/api/v1/resumes/{resume_id}/builder",
                    headers={"Authorization": f"Bearer {account['access_token']}"},
                )
                result["builder_http_status"] = builder_status
                result["builder_response"] = builder
            break
        await asyncio.sleep(poll_interval)
    else:
        result["final_status"] = "timeout"
    return result


def quality_row(result: dict[str, Any], sample: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    pdf_path = (output_dir / sample["split_pdf"]).resolve()
    source = source_text(pdf_path)
    builder = result.get("builder_response") or {}
    modules = builder.get("modules") or builder.get("modules_data", {}).get("modules", []) if isinstance(builder, dict) else []
    module_types = [item.get("module_type") for item in modules if isinstance(item, dict)]
    parsed_text = flatten(modules)
    source_urls = sorted({normalize_url(x) for x in URL_RE.findall(source)})
    parsed_urls = sorted({normalize_url(x) for x in URL_RE.findall(parsed_text)})
    source_emails = sorted({x.lower() for x in EMAIL_RE.findall(source)})
    parsed_emails = sorted({x.lower() for x in EMAIL_RE.findall(parsed_text)})
    source_phones = sorted(set(PHONE_RE.findall(source)))
    parsed_phones = sorted(set(PHONE_RE.findall(parsed_text)))
    return {
        "sample_id": sample["sample_id"],
        "resume_id": result.get("resume_id"),
        "final_status": result.get("final_status"),
        "ready_elapsed_seconds": result.get("ready_elapsed_seconds"),
        "builder_http_status": result.get("builder_http_status"),
        "module_count": len(module_types),
        "module_types": ",".join(module_types),
        "source_characters": len(source),
        "parsed_characters": len(parsed_text),
        "source_url_count": len(source_urls),
        "parsed_url_count": len(parsed_urls),
        "url_recall": round(sum(url in parsed_urls for url in source_urls) / len(source_urls), 4) if source_urls else None,
        "source_email_count": len(source_emails),
        "parsed_email_count": len(parsed_emails),
        "email_recall": round(sum(value in parsed_emails for value in source_emails) / len(source_emails), 4) if source_emails else None,
        "source_phone_count": len(source_phones),
        "parsed_phone_count": len(parsed_phones),
        "phone_recall": round(sum(value in parsed_phones for value in source_phones) / len(source_phones), 4) if source_phones else None,
        "manual_quality_status": "待人工核对：字段语义、模块顺序、链接归属、跨页污染",
    }


async def run(args: argparse.Namespace) -> None:
    output_dir = args.output_dir.resolve()
    manifest = json.loads((output_dir / "source_manifest.json").read_text(encoding="utf-8"))
    samples = [item for item in manifest["samples"] if item["status"] == "ready_for_evaluation"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=60.0)) as client:
        accounts = [await create_account(client, args.base_url, ordinal, stamp) for ordinal in range(1, args.accounts + 1)]
        (output_dir / "runtime_credentials.local.json").write_text(
            json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        queues = [[] for _ in accounts]
        for index, sample in enumerate(samples):
            queues[index % len(queues)].append(sample)

        async def worker(account: dict[str, Any], queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for sample in queue:
                rows.append(
                    await upload_and_poll(
                        client,
                        args.base_url,
                        account,
                        sample,
                        output_dir,
                        args.poll_interval,
                        args.timeout_seconds,
                    )
                )
            return rows

        batches = await asyncio.gather(*(worker(account, queue) for account, queue in zip(accounts, queues)))
    results = [row for batch in batches for row in batch]
    results.sort(key=lambda row: row["sample_id"])
    (output_dir / "upload_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    quality = []
    sample_by_id = {item["sample_id"]: item for item in samples}
    for result in results:
        if result.get("final_status") == "ready":
            quality.append(quality_row(result, sample_by_id[result["sample_id"]], output_dir))
    with (output_dir / "resume_quality.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(quality[0]) if quality else ["sample_id"])
        writer.writeheader()
        writer.writerows(quality)

    ready = [row for row in results if row.get("final_status") == "ready"]
    durations = sorted(row["ready_elapsed_seconds"] for row in ready if row.get("ready_elapsed_seconds") is not None)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "sample_count": len(samples),
        "ready_count": len(ready),
        "failed_count": sum(row.get("final_status") not in {"ready"} for row in results),
        "ready_rate": round(len(ready) / len(samples), 4) if samples else 0,
        "ready_latency_seconds": {
            "min": min(durations) if durations else None,
            "median": durations[len(durations) // 2] if durations else None,
            "max": max(durations) if durations else None,
        },
        "account_count": len(accounts),
        "manual_review_required": [
            "字段语义准确率与模块顺序仍需按 source_manifest 页内证据人工抽样核对。",
            "两个原始 PDF 无嵌入头像；头像/带头像导出需另用合成图片 fixture 测试。",
            "本次数据只代表本地开发环境、当前模型与当前配置，不可直接外推线上 SLA。",
        ],
    }
    (output_dir / "upload_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts") / "career_eval_20260826")
    parser.add_argument("--accounts", type=int, default=4)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
