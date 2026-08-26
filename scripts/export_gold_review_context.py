"""Export model values beside searchable source excerpts for human review."""
from __future__ import annotations

import json
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "career_eval_20260826_v3"
OUTPUT = Path(r"C:\Users\Tianhua\Desktop\Resume_Artifact_Agent_人工审核上下文.md")


def _compact(value: object, limit: int = 500) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    return " ".join(text.split()).replace("|", "\\|")[:limit]


def _source_text(pdf: Path) -> str:
    with fitz.open(pdf) as document:
        return "\n".join(page.get_text() for page in document)


def _excerpt(text: str, value: str) -> str:
    if value:
        pos = text.lower().find(value.lower())
        if pos >= 0:
            return "…" + " ".join(text[max(0, pos - 180) : pos + len(value) + 260].split()) + "…"
    return "（未按模型值在原文中定位到，需人工搜索同义表达或确认缺失）"


def main() -> None:
    uploads = json.loads((ARTIFACT / "upload_results.json").read_text(encoding="utf-8"))
    rows = []
    fields = ("basic_info.name", "basic_info.email", "basic_info.phone", "education", "work_experience", "project_experience", "skills")
    for item in uploads:
        sample = str(item.get("sample_id", ""))
        pdf = ARTIFACT / "samples" / f"{sample}.pdf"
        if not pdf.exists():
            continue
        modules = {
            str(module.get("module_type")): module.get("content", {})
            for module in (item.get("builder_response", {}) or {}).get("modules", [])
            if isinstance(module, dict)
        }
        source = _source_text(pdf)
        rows.append((sample, pdf, source, modules))

    lines = [
        "# Resume Artifact Agent｜人工金标审核上下文",
        "",
        "> 本文件仅为审核辅助，不自动判定正确性。正式判断仍填写《字段语义与检索金标审核表》。",
        "",
    ]
    for sample, pdf, source, modules in rows:
        lines += [f"## {sample}", "", f"原始文件：`{pdf}`", ""]
        for field in fields:
            module_name, _, key = field.partition(".")
            content = modules.get(module_name, {})
            if key and isinstance(content, dict):
                value = content.get(key, "")
            elif module_name in modules:
                value = content
            else:
                value = "未生成"
            value_text = _compact(value)
            lines += [f"### `{field}`", f"- 模型值：`{value_text or '空'}`", f"- 原文定位：{_excerpt(source, value_text)}", "- 你的判断：`1 / 0 / ? / N/A`", ""]
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
