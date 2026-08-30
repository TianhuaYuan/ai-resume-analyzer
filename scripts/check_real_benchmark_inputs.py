from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid JSON input: {path} ({type(exc).__name__})")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--artifact-dir", type=Path, required=True)
    args = p.parse_args()
    root = args.artifact_dir
    credentials = load(root / "runtime_credentials.local.json")
    uploads = load(root / "upload_results.json")
    if not isinstance(credentials, list) or not isinstance(uploads, list):
        raise SystemExit("inputs must be JSON arrays")
    if not credentials or not all(isinstance(x, dict) and x.get("user_id") and x.get("access_token") for x in credentials):
        raise SystemExit("credentials missing user_id/access_token")
    ready = [x for x in uploads if isinstance(x, dict) and x.get("final_status") == "ready" and x.get("resume_id")]
    if not ready:
        raise SystemExit("no ready uploads")
    print(json.dumps({"valid": True, "accounts": len(credentials), "ready_uploads": len(ready)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
