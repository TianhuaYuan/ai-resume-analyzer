"""Measure Agent SSE, preview and export on already uploaded evaluation resumes."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx


def parse_sse(block: str) -> dict[str, Any] | None:
    data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
    if not data:
        return None
    try:
        value = json.loads(data)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return {"type": "protocol_error", "raw": data[:1000]}


async def stream_one(client: httpx.AsyncClient, base: str, token: str, resume_id: int, question: str) -> dict[str, Any]:
    start = time.perf_counter()
    events: list[dict[str, Any]] = []
    buffer = ""
    async with client.stream("POST", f"{base}/api/v1/qa/ask/agent", headers={"Authorization": f"Bearer {token}"}, json={"resume_id": resume_id, "question": question}, timeout=httpx.Timeout(240.0, connect=20.0)) as response:
        result = {"resume_id": resume_id, "http_status": response.status_code, "events": events}
        if response.status_code != 200:
            result["error"] = (await response.aread()).decode("utf-8", errors="replace")[:2000]
            return result
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                event = parse_sse(block)
                if event:
                    event["elapsed_seconds"] = round(time.perf_counter() - start, 3)
                    events.append(event)
        if buffer.strip():
            event = parse_sse(buffer)
            if event:
                event["elapsed_seconds"] = round(time.perf_counter() - start, 3)
                events.append(event)
        result["total_seconds"] = round(time.perf_counter() - start, 3)
        result["terminal_types"] = [e.get("type") for e in events if e.get("type") in {"agent_done", "error", "quota_exceeded", "cancelled"}]
        result["first_event_seconds"] = events[0].get("elapsed_seconds") if events else None
        result["tool_call_count"] = sum(e.get("type") == "tool_call" for e in events)
        return result


async def main(args: argparse.Namespace) -> None:
    root = args.output_dir.resolve()
    creds = json.loads((root / "runtime_credentials.local.json").read_text(encoding="utf-8"))
    rows = json.loads((root / "upload_results.json").read_text(encoding="utf-8"))
    by_user = {int(x["user_id"]): x for x in creds}
    chosen = [x for x in rows if x.get("final_status") == "ready" and x.get("resume_id") in args.resume_ids]
    results: dict[str, Any] = {"base_url": args.base_url, "generated_at": time.time(), "agent": [], "preview_export": []}
    async with httpx.AsyncClient() as client:
        for row in chosen:
            account = by_user[int(row["user_id"])]
            token = account["access_token"]
            results["agent"].append(await stream_one(client, args.base_url, token, int(row["resume_id"]), args.question))
            item: dict[str, Any] = {"resume_id": row["resume_id"]}
            for path in (f"/api/v1/resumes/{row['resume_id']}/preview", f"/api/v1/resumes/{row['resume_id']}/export?format=markdown", f"/api/v1/resumes/{row['resume_id']}/export?format=pdf"):
                response = await client.get(args.base_url + path, headers={"Authorization": f"Bearer {token}"}, timeout=120.0)
                item[path.split("?")[0].split("/")[-1] + ("_" + path.split("=", 1)[1] if "=" in path else "")] = {"status": response.status_code, "content_type": response.headers.get("content-type"), "size": len(response.content), "cache_hit": response.headers.get("x-cache-hit")}
            results["preview_export"].append(item)
    (root / "runtime_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"agent_runs": len(results["agent"]), "preview_export_runs": len(results["preview_export"])}, ensure_ascii=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8085")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--resume-ids", type=int, nargs="+", required=True)
    p.add_argument("--question", default="请基于当前简历回答：候选人的核心技能、一个项目亮点和最适合的岗位方向；只能使用简历证据，不能补充原文没有的信息。")
    asyncio.run(main(p.parse_args()))
