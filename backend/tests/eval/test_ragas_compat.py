"""test_ragas_compat — 转 RAGAS dict / DeepEval cases 的形状与字段。"""

from __future__ import annotations

from eval.aggregator import aggregate
from eval.protocol import EvalDataset, EvalEntry, ExecutorResult, JudgeResult
from eval.ragas_compat import to_deepeval_test_cases, to_ragas_dataset


def _dataset() -> EvalDataset:
    raw = {
        "meta": {"name": "mini", "version": "0.0.1"},
        "resumes": {str(i): {"file": f"r{i}.txt"} for i in range(1, 5)},
        "samples": [
            {
                "id": f"q{i}", "resume_id": i, "category": c, "difficulty": "easy",
                "question": f"问题{i}", "reference_answer": f"参考{i}",
                "keywords": [], "asker": "hr", "should_answer": True,
            }
            for i, c in enumerate(["factual", "reasoning", "comparative", "rejection"], start=1)
        ],
    }
    return EvalDataset.from_dict(raw)


def _entries(n: int = 3) -> list[EvalEntry]:
    out = []
    for i in range(n):
        jr = JudgeResult(1.0, 1.0, 0.0, 1.0, "r", "m")
        out.append(EvalEntry(
            sample_id=f"s{i}", category="factual", difficulty="easy", asker="hr",
            question=f"q{i}", answer=f"a{i}", reference_answer=f"ref{i}",
            params={}, executor_result=ExecutorResult(answer=f"a{i}", sources=[{"text": f"ctx{i}"}]),
            judge_result=jr, composite=jr.composite, needs_reflexion=jr.needs_reflexion,
            latency_ms=10.0 * i,
        ))
    return out


def test_to_ragas_dataset_shape():
    ds = _dataset()
    entries = _entries(3)
    rag = to_ragas_dataset(ds, entries)
    assert set(rag.keys()) == {"question", "answer", "contexts", "reference"}
    assert rag["question"] == ["q0", "q1", "q2"]
    assert rag["answer"] == ["a0", "a1", "a2"]
    assert rag["reference"] == ["ref0", "ref1", "ref2"]
    assert rag["contexts"] == [["ctx0"], ["ctx1"], ["ctx2"]]
    # 不依赖 aggregate
    assert aggregate(entries)["avg_composite"] == 1.0


def test_to_deepeval_test_cases_shape():
    ds = _dataset()
    entries = _entries(2)
    cases = to_deepeval_test_cases(ds, entries)
    assert len(cases) == 2
    assert cases[0] == {
        "input": "q0",
        "actual_output": "a0",
        "retrieval_context": ["ctx0"],
        "expected_output": "ref0",
    }
