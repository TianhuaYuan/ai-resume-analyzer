"""Evaluate one ready resume against the ten supplied JD sections."""
from __future__ import annotations
import argparse, asyncio, json, re, time
from pathlib import Path
import httpx

async def main(args: argparse.Namespace) -> None:
    root = args.output_dir.resolve()
    creds = json.loads((root / "runtime_credentials.local.json").read_text(encoding="utf-8"))
    rows = json.loads((root / "upload_results.json").read_text(encoding="utf-8"))
    row = next(x for x in rows if int(x.get("resume_id")) == args.resume_id)
    account = next(x for x in creds if int(x["user_id"]) == int(row["user_id"]))
    text = Path(args.jd_file).read_text(encoding="utf-8")
    matches = list(re.finditer(r"(?m)^# 岗位\s*(\d+)[：:](.*?)(?=^# 岗位\s*\d+[：:]|\Z)", text, re.S))
    if len(matches) != 10:
        raise RuntimeError(f"expected 10 JD sections, got {len(matches)}")
    out = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
        semaphore = asyncio.Semaphore(3)
        async def one(m):
            async with semaphore:
                started = time.perf_counter()
                try:
                    resp = await client.post(
                        f"{args.base_url}/api/v1/resumes/{args.resume_id}/match-jd",
                        headers={"Authorization": f"Bearer {account['access_token']}"},
                        json={"jd_text": m.group(0)[:12000]},
                    )
                    try: body = resp.json()
                    except Exception: body = {"raw": resp.text[:2000]}
                    return {"jd_number": int(m.group(1)), "title": m.group(2).strip(), "status": resp.status_code, "elapsed_seconds": round(time.perf_counter()-started, 3), "result": body}
                except Exception as exc:
                    return {"jd_number": int(m.group(1)), "title": m.group(2).strip(), "status": 0, "elapsed_seconds": round(time.perf_counter()-started, 3), "error": f"{type(exc).__name__}: {exc}"}
        out = await asyncio.gather(*(one(m) for m in matches))
    (root / "jd_match_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(out), "ok": sum(x["status"] == 200 for x in out), "elapsed_seconds": round(sum(x["elapsed_seconds"] for x in out), 3)}, ensure_ascii=False))

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--base-url", default="http://127.0.0.1:8081"); p.add_argument("--output-dir", type=Path, required=True); p.add_argument("--resume-id", type=int, required=True); p.add_argument("--jd-file", type=Path, required=True); asyncio.run(main(p.parse_args()))
