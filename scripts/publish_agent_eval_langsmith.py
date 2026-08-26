"""Publish the deterministic Agent golden-task evaluation to LangSmith.

Only synthetic task instructions and aggregate scores are uploaded; resume PII is
never sent by this script. Configure LANGCHAIN_API_KEY in backend/.env.dev.
"""
from __future__ import annotations
import asyncio, json, os, sys
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend" / ".env.dev", override=False)
sys.path.insert(0, str(ROOT / "backend"))

async def main() -> None:
    from tests.agent_eval.golden_tasks import ALL_TASKS
    from tests.agent_eval.harness import run_evals, summarize
    from langsmith import Client

    if not os.getenv("LANGCHAIN_API_KEY"):
        raise SystemExit("LANGCHAIN_API_KEY 未配置")
    reports = await run_evals(ALL_TASKS, trials=1)
    summary = summarize(reports)
    client = Client()
    dataset_name = os.getenv("LANGCHAIN_DATASET", "resume-artifact-agent-golden-tasks")
    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
    except Exception:
        dataset = client.create_dataset(dataset_name=dataset_name, description="Synthetic golden tasks for ReAct trajectory regression")
    existing = {str(x.inputs.get("name")) for x in client.list_examples(dataset_id=dataset.id)}
    examples = [
        {"name": task.name, "instruction": task.instruction, "required_outputs": list(task.required_outputs), "gold_actions": [{"name": a.name, "args": a.args} for a in task.gold_actions]}
        for task in ALL_TASKS if task.name not in existing
    ]
    if examples:
        client.create_examples(inputs=[{"name": e["name"], "instruction": e["instruction"]} for e in examples], outputs=[{"required_outputs": e["required_outputs"], "gold_actions": e["gold_actions"]} for e in examples], dataset_id=dataset.id)
    for task_name, task_summary in summary["tasks"].items():
        run_id = uuid4()
        client.create_run(run_id=run_id, name=f"golden_eval:{task_name}", run_type="chain", inputs={"task": task_name}, outputs=task_summary, extra={"metadata": {"eval_version": "v1", "synthetic": True}}, tags=["resume-artifact-agent", "golden-eval"])
        client.update_run(run_id, end_time=datetime.now(timezone.utc))
    result = {"dataset_id": str(dataset.id), "dataset_name": dataset_name, "summary": summary, "synthetic_only": True}
    artifact = ROOT / "artifacts" / "career_eval_20260826_v3" / "langsmith_eval_results.json"
    artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
