from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    cases = [json.loads(x) for x in (root / "datasets/cases.jsonl").read_text(encoding="utf-8").splitlines()]
    cases = [c for c in cases if c.get("deep_research")][:15]
    lines = ["# Deep Research 人工 Gold 审核包", "", "请把模型实际输出粘贴到对应位置，再对照原始简历/JD/来源证据审核。没有实际输出时不要填写结论。", ""]
    for i, c in enumerate(cases, 1):
        e = c["expected"]
        lines += [f"## {i}. {c['case_id']}", "", f"- 类别：{c['category']} / 风险：{c['risk']}", f"- 任务：{c['task_type']}", f"- 输入提示：{c['input']['prompt']}", f"- 审核要求：引用证据={e['must_cite_evidence']}；说明不确定性={e['must_state_uncertainty']}；拒绝不安全请求={e['must_refuse_unsafe']}", "", "### 模型实际输出", "", "（粘贴在这里）", "", "### 证据核对", "", "- evidence_supported（true/false）：", "- citation_correct（true/false）：", "- conflict_resolution（none 或具体采信来源）：", "- unsafe_should_refuse（true/false）：", "- reviewer_notes：", "- reviewer_id：", "- reviewed_at：", "", "---", ""]
    out = root / "datasets/deep_research_review_packet.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
