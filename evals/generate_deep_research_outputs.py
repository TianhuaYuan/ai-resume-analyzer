from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.config import settings
from services.rag.clients import get_chat_client


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    cases = [json.loads(x) for x in (root / "datasets/cases.jsonl").read_text(encoding="utf-8") .splitlines() if x.strip()]
    cases = [c for c in cases if c.get("deep_research")][:15]
    source_paths = [
        Path("D:/Edge/简历/资料/Agent应用开发工程师真实简历.md"),
        Path("D:/Edge/简历/资料/AI产品经理真实简历.md"),
        Path("D:/Edge/简历/资料/深圳地区AI产品岗位真实招聘信息.md"),
        Path("D:/Edge/简历/资料/深圳地区AI Agent岗位真实招聘信息.md"),
    ]
    source_bundle = "\n\n".join(
        f"[SOURCE {path.name}]\n{path.read_text(encoding='utf-8', errors='replace')[:12000]}"
        for path in source_paths if path.exists()
    )
    client = get_chat_client()
    rows = []
    for case in cases:
        prompt = (
            "你是证据审查 Agent。仅根据下面任务提示回答；没有原始证据时必须明确说证据不足，禁止编造。"
            "输出 JSON：claim、citations（数组）、uncertainty、refused、conflicts。\n"
            f"任务：{case['input']['prompt']}\n\n可核对的真实资料：\n{source_bundle}"
        )
        try:
            response = await client.chat.completions.create(
                model=settings.CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1200,
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "enabled"}},
                reasoning_effort=settings.THINKING_EFFORT,
            )
            message = response.choices[0].message
            usage = getattr(response, "usage", None)
            content = message.content or ""
            rows.append({"case_id": case["case_id"], "model": settings.CHAT_MODEL, "status": "ok" if content else "empty_content",
                         "output": content, "reasoning_content_present": bool(getattr(message, "reasoning_content", None)),
                         "token_usage": {"prompt_tokens": getattr(usage, "prompt_tokens", 0), "completion_tokens": getattr(usage, "completion_tokens", 0)} if usage else None,
                         "human_review_required": True})
        except Exception as exc:
            rows.append({"case_id": case["case_id"], "model": settings.CHAT_MODEL, "status": "error",
                         "error_type": type(exc).__name__, "error": str(exc)[:500], "human_review_required": True})
    Path(args.out).write_text(json.dumps({"cases": len(rows), "rows": rows, "note": "raw model outputs; not gold"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cases": len(rows), "ok": sum(x["status"] == "ok" for x in rows), "errors": sum(x["status"] == "error" for x in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
