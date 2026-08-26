"""Run a bounded Agent quality matrix against the uploaded career samples.

The script deliberately uses one isolated conversation per sample and keeps
the request rate below the development API limit. It records protocol and
latency evidence; it does not invent semantic accuracy labels.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx


QUESTIONS = (
    "只根据当前简历回答：候选人的核心技能、最有说服力的一段经历是什么？每个结论标注对应证据，不要补写原文没有的事实。",
    "请基于当前简历判断最适合的岗位方向，并说明需要调用哪些简历检索或分析工具；回答必须区分原文事实和推断。",
    "请检查当前简历中可能影响投递的一个问题，给出可执行建议和证据位置；如果证据不足，请明确说无法判断。",
)
TERMINALS = {"agent_done", "error", "quota_exceeded", "cancelled"}


def parse_sse(block: str) -> dict[str, Any] | None:
    data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
    if not data:
        return None
    try:
        value = json.loads(data)
    except json.JSONDecodeError:
        return {"type": "protocol_error", "raw": data[:1000]}
    return value if isinstance(value, dict) else {"type": "protocol_error", "raw": data[:1000]}


class RateLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.lock = asyncio.Lock()
        self.next_at = 0.0

    async def wait(self) -> None:
        async with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_at - now)
            self.next_at = max(now, self.next_at) + self.interval
        if delay:
            await asyncio.sleep(delay)


async def run_one(
    client: httpx.AsyncClient,
    limiter: RateLimiter,
    base_url: str,
    token: str,
    user_id: int,
    resume_id: int,
    sample_id: str,
    question: str,
) -> dict[str, Any]:
    await limiter.wait()
    started = time.perf_counter()
    payload = {"resume_id": resume_id, "question": question}
    result: dict[str, Any] = {
        "sample_id": sample_id,
        "user_id": user_id,
        "resume_id": resume_id,
        "question": question,
        "events": [],
    }
    for attempt in range(3):
        try:
            async with client.stream(
                "POST",
                f"{base_url.rstrip('/')}/api/v1/qa/ask/agent",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
                timeout=httpx.Timeout(240.0, connect=20.0),
            ) as response:
                result["http_status"] = response.status_code
                if response.status_code == 429 and attempt < 2:
                    await asyncio.sleep(15 * (attempt + 1))
                    await limiter.wait()
                    continue
                if response.status_code != 200:
                    result["error"] = (await response.aread()).decode("utf-8", errors="replace")[:2000]
                    break
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        event = parse_sse(block)
                        if event:
                            event["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                            result["events"].append(event)
                if buffer.strip():
                    event = parse_sse(buffer)
                    if event:
                        event["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                        result["events"].append(event)
                break
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            result["error"] = type(exc).__name__
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
                await limiter.wait()
                continue
            break
    result["total_seconds"] = round(time.perf_counter() - started, 3)
    result["terminal_types"] = [e.get("type") for e in result["events"] if e.get("type") in TERMINALS]
    result["tool_result_count"] = sum(e.get("type") == "tool_result" for e in result["events"])
    result["tool_error_count"] = sum(e.get("type") == "tool_error" for e in result["events"])
    usage = [e.get("token_usage") for e in result["events"] if isinstance(e.get("token_usage"), dict)]
    result["token_usage"] = usage[-1] if usage else None
    return result


async def main(args: argparse.Namespace) -> None:
    root = args.output_dir.resolve()
    credentials = json.loads((root / "runtime_credentials.local.json").read_text(encoding="utf-8"))
    accounts = {int(row["user_id"]): row for row in credentials}
    uploads = json.loads((root / "upload_results.json").read_text(encoding="utf-8"))
    rows = [row for row in uploads if row.get("final_status") == "ready" and int(row["user_id"]) in accounts]
    rows.sort(key=lambda row: str(row.get("sample_id", row.get("resume_id"))))
    limiter = RateLimiter(args.interval)
    semaphore = asyncio.Semaphore(args.concurrency)

    async def bounded(row: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await run_one(
                client,
                limiter,
                args.base_url,
                accounts[int(row["user_id"])]["access_token"],
                int(row["user_id"]),
                int(row["resume_id"]),
                str(row.get("sample_id", row["resume_id"])),
                QUESTIONS[int(row["resume_id"]) % len(QUESTIONS)],
            )

    async with httpx.AsyncClient() as client:
        # Refresh expired local tokens without printing credentials. Login is
        # intentionally sequential and happens before the rate-limited matrix.
        for account in accounts.values():
            try:
                response = await client.post(
                    f"{args.base_url.rstrip('/')}/api/v1/auth/login",
                    json={"email": account["email"], "password": account["password"]},
                    timeout=20.0,
                )
                if response.status_code == 200:
                    account["access_token"] = response.json().get("access_token", account["access_token"])
            except (httpx.HTTPError, ValueError):
                pass
        results = await asyncio.gather(*(bounded(row) for row in rows))
    output = {
        "generated_at": time.time(),
        "base_url": args.base_url,
        "sample_count": len(results),
        "question_count": len(QUESTIONS),
        "rate_interval_seconds": args.interval,
        "results": results,
    }
    (root / "agent_matrix_results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "samples": len(results),
        "http_200": sum(r.get("http_status") == 200 for r in results),
        "single_terminal": sum(len(r.get("terminal_types", [])) == 1 for r in results),
        "with_tool_error": sum(r.get("tool_error_count", 0) > 0 for r in results),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8085")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--interval", type=float, default=8.5, help="seconds between request starts")
    asyncio.run(main(parser.parse_args()))
