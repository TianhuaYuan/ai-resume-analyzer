"""Build a compact human-gold review sheet from the existing evaluation manifest."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=repo / "artifacts" / "career_eval_20260826_v3")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    artifact = args.artifact_dir.resolve()
    rows = list(csv.DictReader((artifact / "resume_quality.csv").open(encoding="utf-8-sig")))
    uploads = json.loads((artifact / "upload_results.json").read_text(encoding="utf-8"))
    model_by_sample = {
        str(row.get("sample_id")): row.get("builder_response", {}).get("modules", [])
        for row in uploads
        if isinstance(row.get("builder_response"), dict)
    }
    out = (args.output or artifact / "human_gold_review.md").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Resume Artifact Agent｜字段语义与检索金标审核表",
        "",
        "> 这份表只要求人工判断，不要求重新整理 PDF。每行填 `1`（正确）、`0`（错误）或 `N/A`（原文没有该字段）；不确定填 `?`。只有填完后，才能计算字段语义准确率和检索相关性指标。",
        "",
        "## A. 字段语义金标",
        "",
        "| 样本 | 字段 | 模型值/模块状态 | 原文证据位置或摘录 | 判断 | 备注 |",
        "|---|---|---|---|---:|---|",
    ]
    fields = ("basic_info.name", "basic_info.email", "basic_info.phone", "education", "work_experience", "project_experience", "skills")
    for row in rows:
        sample = row.get("sample_id", "")
        module_types = set(filter(None, (row.get("module_types") or "").split(",")))
        modules = {str(item.get("module_type")): item.get("content", {}) for item in model_by_sample.get(sample, []) if isinstance(item, dict)}
        for field in fields:
            module = field.split(".", 1)[0]
            content = modules.get(module, {})
            if field.count(".") == 1 and module == "basic_info":
                value = content.get(field.split(".", 1)[1], "") if isinstance(content, dict) else ""
            elif module in module_types:
                value = f"已解析（{len(content.get('items', [])) if isinstance(content, dict) else 0} 条）"
            else:
                value = "未生成"
            value = str(value).replace("|", "\\|").replace("\n", " ")[:240]
            current = value or ("已解析" if module in module_types else "未生成")
            lines.append(f"| {sample} | {field} | {current} |  |  |  |")
    lines += [
        "",
        "## B. 检索相关性金标",
        "",
        "> 对每个 JD 的 Top-5 证据片段判断是否真正支持该结论：`1`=相关且支持，`0`=不相关，`?`=无法判断。只看证据与问题的对应关系，不评价文案是否好看。",
        "",
        "| JD | 样本 | Top-K | 证据摘要/链接 | 相关性判断 | 是否支持结论 | 备注 |",
        "|---|---|---:|---|---:|---:|---|",
    ]
    jd_count = 10
    for idx in range(1, jd_count + 1):
        for rank in range(1, 6):
            lines.append(f"| jd_{idx:02d} | resume_11 | {rank} |  |  |  |  |")
    lines += [
        "",
        "## C. 计算规则",
        "",
        "- 字段语义准确率 = `判断为 1 的字段数 / 已标注且可核验字段数`；模块是否存在不能替代字段值是否正确。",
        "- 检索 Recall@K = `Top-K 中被判断为相关的证据数 / 该问题全部相关证据数`；没有相关证据金标时不要填写。",
        "- RAG faithfulness 需要逐条检查回答结论是否能被证据支持；不能用 HTTP 200 或回答长度替代。",
        "- 当前样本清单以 `source_manifest.json` 为准；第一批重复占位“简历6”不计入。",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
