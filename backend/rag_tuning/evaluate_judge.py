"""阶段7 —— LLM-as-Judge 评估器（三维度加权 + Reflexion 闭环）。

职责：
1. 读取 golden_set.json（简历问答评测集）。
2. 把每条问题跑过真实 RAG 管线（Agentic 图，懒加载避免与阶段11 重构冲突），拿到答案与来源。
3. 用 judge_client（DeepSeek）对每条答案打三维度分，算 composite 加权（完整性0.4/准确性0.4/来源可信度0.2）。
4. composite < 0.6 标记 needs_reflexion（对应图中 SELF_REFLECTION_NODE 自纠正闭环）。
5. 输出 eval_report.json（每条得分 + 汇总 + 按维度分组）。

设计要点（利于测试与不破坏其他阶段）：
- 图导入必须在函数内懒加载：from services.agentic_rag.graph import create_agentic_rag_graph。
  阶段11 正在合并 mcp_graph 进 graph.py，但 graph.py 路径稳定，这样并发重构不会让本模块 import 挂。
- 纯函数 compute_composite / needs_reflexion 与可注入的 judge_fn / generate_fn：
  测试只需 monkeypatch judge_fn（fake judge）即可验证打分与 Reflexion 逻辑，绝不触网。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 确保能导入 backend 包（与现有 evaluate.py 一致）
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import settings
from rag_tuning import judge_client
from rag_tuning.judge_client import JudgeResult, WEIGHTS, REFLEXION_THRESHOLD

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"
REPORT_PATH = Path(__file__).parent / "eval_report.json"

# judge_fn 签名：async (question, answer, reference, sources) -> JudgeResult
JudgeFn = Callable[[str, str, str, Optional[list[dict]]], Awaitable[JudgeResult]]
# generate_fn 签名：async (entry) -> (answer, sources)
GenerateFn = Callable[[dict], Awaitable[tuple[str, list[dict]]]]


# ───────────────────── 纯打分逻辑（测试主战场）─────────────────────
def compute_composite(
    completeness: float, accuracy: float, source_credibility: float
) -> float:
    """三维度加权综合分：完整性0.4 + 准确性0.4 + 来源可信度0.2。"""
    return (
        completeness * WEIGHTS["completeness"]
        + accuracy * WEIGHTS["accuracy"]
        + source_credibility * WEIGHTS["source_credibility"]
    )


def needs_reflexion(composite: float) -> bool:
    """composite < 0.6 → 需要 Reflexion 自纠正（严格小于，0.6 不触发）。"""
    return composite < REFLEXION_THRESHOLD


# ───────────────────── 离线启发式 Judge（仅用于无密钥冒烟验收，非生产）─────────────────────
async def _local_heuristic_judge(
    question: str,
    answer: str,
    reference: str,
    sources: list[dict] | None,
) -> JudgeResult:
    """不依赖任何 LLM 的本地启发式评分，仅用于 --fake-judge 离线冒烟。

    用『预期关键词命中率』近似三维度：覆盖/准确看答案是否命中参考关键词，
    来源可信度看关键词是否也能在检索来源里找到。生产评估请用 DeepSeek Judge。
    """

    def _hit_rate(text: str, keywords: list[str]) -> float:
        if not keywords:
            return 1.0 if text.strip() else 0.3
        hit = sum(1 for k in keywords if k and k in text)
        return hit / len(keywords)

    ref_kw = list(set(_extract_keywords(reference)))
    src_text = " ".join(s.get("text", "") for s in (sources or []))
    src_kw = list(set(_extract_keywords(reference)))  # 以参考关键词为基准校验来源

    completeness = _hit_rate(answer, ref_kw)
    accuracy = _hit_rate(answer, ref_kw)
    source_credibility = _hit_rate(src_text, src_kw) if src_text.strip() else 0.5
    rationale = (
        f"[离线启发式] 答案命中参考关键词 {completeness:.2f}，"
        f"来源命中 {source_credibility:.2f}（非 DeepSeek 真实评分）"
    )
    return JudgeResult(
        completeness=completeness,
        accuracy=accuracy,
        source_credibility=source_credibility,
        rationale=rationale,
        model="local-heuristic(fake)",
    )


def _extract_keywords(text: str) -> list[str]:
    """极简关键词提取：按非中文/英文词边界切分，过滤停用短串。"""
    if not text:
        return []
    # 去掉标点，按空白/常见分隔切分
    parts = re.split(r"[\s，。、；：（）()\[\]【】\"'.,!?]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 2]


# ───────────────────── 单条评估 ─────────────────────
async def evaluate_entry(
    entry: dict,
    answer: str,
    sources: list[dict] | None,
    judge_fn: JudgeFn = judge_client.judge,
) -> dict:
    """对一条『已有答案』的评测项打分，返回评估记录。

    answer/sources 由调用方提供（真实跑图 或 测试注入），本函数只负责评估。
    """
    result = await judge_fn(
        entry["question"], answer, entry["reference_answer"], sources
    )
    composite = compute_composite(
        result.completeness, result.accuracy, result.source_credibility
    )
    return {
        "id": entry["id"],
        "category": entry.get("category"),
        "answer_type": entry.get("answer_type"),
        "question": entry["question"],
        "answer": answer,
        "reference_answer": entry["reference_answer"],
        "scores": result.to_dict(),
        "composite": round(composite, 4),
        "needs_reflexion": needs_reflexion(composite),
    }


# ───────────────────── 真实 RAG 管线（懒加载图）─────────────────────
async def _run_graph(entry: dict) -> tuple[str, list[dict]]:
    """懒加载 Agentic RAG 图并跑一条 QA，返回 (final_answer, sources)。

    仅当 run_graph=True 时调用；测试默认不调用，避免依赖 Chroma/Embedding/LLM 真实环境。
    """
    from services.agentic_rag.graph import create_agentic_rag_graph

    graph = create_agentic_rag_graph()
    resume_id = int(entry["resume_id"])
    initial_state = {
        "question": entry["question"],
        "resume_id": resume_id,
        "rewritten_query": "",
        "route_decision": "search",
        "chunks": [],
        "search_round": 0,
        "answer": "",
        "sources": [],
        "eval_score": 0.0,
        "eval_feedback": "",
        "should_retry": False,
        "completeness_score": 0.0,
        "accuracy_score": 0.0,
        "source_credibility_score": 0.0,
        "reflection_result": "",
        "missing_info": [],
        "supplement_queries": [],
        "reflection_round": 0,
        "final_answer": "",
        "final_sources": [],
        "trace": {},
        "tool_errors": [],
    }
    result = await graph.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )
    answer = result.get("final_answer") or result.get("answer", "")
    sources = result.get("sources", []) or []
    return answer, sources


# ───────────────────── 数据集校验 ─────────────────────
_REQUIRED_QA_FIELDS = {"id", "resume_id", "category", "question", "reference_answer"}


def validate_golden_set(path: Path = GOLDEN_SET_PATH) -> dict:
    """校验 golden_set.json 结构完整、条目数达标、维度覆盖。

    - 必须有 resumes 字典与 qa 列表；
    - 每条 qa 含必填字段且 resume_id 能对应到 resumes；
    - qa 条目数 ≥ 10；
    - category 覆盖至少 4 个不同维度（避免评测偏科）。
    返回解析后的 {'resumes':..., 'qa':...} 供评估使用。
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("golden_set.json 顶层应为对象（含 resumes 与 qa）")

    resumes = data.get("resumes")
    qa = data.get("qa")
    if not isinstance(resumes, dict) or not resumes:
        raise ValueError("golden_set.json 缺少非空 resumes 字段")
    if not isinstance(qa, list):
        raise ValueError("golden_set.json 的 qa 应为列表")

    if len(qa) < 10:
        raise ValueError(f"qa 条目数需 ≥ 10，实际 {len(qa)}")

    for i, e in enumerate(qa):
        missing = _REQUIRED_QA_FIELDS - set(e.keys())
        if missing:
            raise ValueError(f"第 {i} 条（id={e.get('id')}）缺少字段：{missing}")
        if str(e["resume_id"]) not in {str(k) for k in resumes.keys()}:
            raise ValueError(
                f"第 {i} 条 resume_id={e['resume_id']} 在 resumes 中不存在"
            )

    categories = {e.get("category") for e in qa}
    if len(categories) < 4:
        raise ValueError(f"qa 维度覆盖不足（需≥4，实际 {sorted(categories)}）")

    return data


# ───────────────────── 汇总 ─────────────────────
def _aggregate(per_entry: list[dict]) -> dict:
    composites = [r["composite"] for r in per_entry]
    avg = sum(composites) / len(composites) if composites else 0.0
    reflexion_count = sum(1 for r in per_entry if r["needs_reflexion"])

    by_category: dict[str, dict[str, Any]] = {}
    for r in per_entry:
        cat = r.get("category") or "unknown"
        bucket = by_category.setdefault(
            cat, {"count": 0, "composite_sum": 0.0, "reflexion_count": 0}
        )
        bucket["count"] += 1
        bucket["composite_sum"] += r["composite"]
        bucket["reflexion_count"] += 1 if r["needs_reflexion"] else 0
    for cat, b in by_category.items():
        b["avg_composite"] = round(b["composite_sum"] / b["count"], 4)
        del b["composite_sum"]

    return {
        "entry_count": len(per_entry),
        "avg_composite": round(avg, 4),
        "reflexion_count": reflexion_count,
        "reflexion_rate": round(reflexion_count / len(per_entry), 4) if per_entry else 0.0,
        "judge_model": settings.JUDGE_MODEL if settings.JUDGE_ENABLED else "disabled",
        "weights": WEIGHTS,
        "reflexion_threshold": REFLEXION_THRESHOLD,
        "by_category": by_category,
    }


# ───────────────────── 主评估流程 ─────────────────────
async def run_evaluation(
    data: dict,
    judge_fn: JudgeFn = judge_client.judge,
    generate_fn: Optional[GenerateFn] = None,
    run_graph: bool = True,
) -> dict:
    """跑全量评测。

    run_graph=True：用真实 Agentic 图生成答案（需 RAG 环境）。
    run_graph=False：从 qa 项读取预置 answer/sources（离线验收与测试用）。
    """
    generate_fn = generate_fn or _run_graph
    qa = data["qa"]
    per_entry: list[dict] = []

    for entry in qa:
        if run_graph:
            answer, sources = await generate_fn(entry)
        else:
            # 离线模式：使用条目内预置 answer（便于无环境验收），缺省空串
            answer = entry.get("answer") or ""
            sources = entry.get("sources") or []
        rec = await evaluate_entry(entry, answer, sources, judge_fn=judge_fn)
        per_entry.append(rec)

    report = {
        "summary": _aggregate(per_entry),
        "per_entry": per_entry,
    }
    return report


def save_report(report: dict, path: Path = REPORT_PATH) -> None:
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[SAVE] 评估报告已写出：{path}")


# ───────────────────── CLI 入口 ─────────────────────
async def main() -> None:
    parser = argparse.ArgumentParser(description="阶段7 LLM-as-Judge 评估器")
    parser.add_argument(
        "--golden-set", type=str, default=str(GOLDEN_SET_PATH), help="评测集路径"
    )
    parser.add_argument(
        "--report", type=str, default=str(REPORT_PATH), help="评估报告输出路径"
    )
    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="离线模式：不跑真实 RAG 图，使用条目内预置 answer（用于无环境验收）",
    )
    parser.add_argument(
        "--fake-judge",
        action="store_true",
        help="离线冒烟：用本地启发式 Judge 替代 DeepSeek（无需密钥，结果仅用于验证管线）",
    )
    args = parser.parse_args()

    print("[LOAD] 校验数据集 ...")
    data = validate_golden_set(Path(args.golden_set))
    print(
        f"   简历 {len(data['resumes'])} 份，评测项 {len(data['qa'])} 条，"
        f"维度 {sorted({e.get('category') for e in data['qa']})}"
    )

    run_graph = not args.no_graph
    if run_graph and not settings.JUDGE_ENABLED and not args.fake_judge:
        print(
            "[WARN] JUDGE_ENABLED=false，DeepSeek Judge 未启用，"
            "真实评估将失败。可加 --fake-judge 跑离线冒烟，或设置 JUDGE_ENABLED=true。"
        )

    judge_fn: JudgeFn = _local_heuristic_judge if args.fake_judge else judge_client.judge
    print(f"[RUN] 评估（run_graph={run_graph}, judge={'fake' if args.fake_judge else 'deepseek'}）...")
    report = await run_evaluation(data, judge_fn=judge_fn, run_graph=run_graph)
    save_report(report, Path(args.report))

    s = report["summary"]
    print("\n========== 评估汇总 ==========")
    print(f"  评测项: {s['entry_count']}")
    print(f"  平均 composite: {s['avg_composite']}")
    print(f"  需 Reflexion: {s['reflexion_count']} 条（{s['reflexion_rate']*100:.1f}%）")
    print(f"  维度分布: {s['by_category']}")


if __name__ == "__main__":
    asyncio.run(main())
