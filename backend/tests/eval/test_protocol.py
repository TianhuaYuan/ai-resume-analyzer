"""test_protocol — 数据契约：加载、校验、JudgeResult.composite 数学。"""

from __future__ import annotations

import json

from eval.protocol import EvalDataset, JudgeResult, TestSample


def _mini_dataset() -> dict:
    return {
        "meta": {"name": "mini", "version": "0.0.1"},
        "resumes": {
            "1": {"file": "r1.txt"},
            "2": {"file": "r2.txt"},
            "3": {"file": "r3.txt"},
            "4": {"file": "r4.txt"},
        },
        "samples": [
            {
                "id": "q1", "resume_id": 1, "category": "factual", "difficulty": "easy",
                "question": "学历？", "reference_answer": "本科",
                "keywords": ["本科"], "split": "tuning", "asker": "hr", "should_answer": True,
            },
            {
                "id": "q2", "resume_id": 2, "category": "reasoning", "difficulty": "medium",
                "question": "为什么离职？", "reference_answer": "寻求更好平台",
                "keywords": ["平台"], "split": "tuning", "asker": "hr", "should_answer": False,
            },
            {
                "id": "q3", "resume_id": 3, "category": "comparative", "difficulty": "hard",
                "question": "A 与 B 区别？", "reference_answer": "区别在 X",
                "keywords": ["X"], "split": "eval", "asker": "tech_interviewer", "should_answer": True,
            },
            {
                "id": "q4", "resume_id": 4, "category": "rejection", "difficulty": "medium",
                "question": "秘密信息？", "reference_answer": "未提及",
                "keywords": [], "split": "eval", "asker": "product_manager", "should_answer": False,
            },
        ],
    }


def test_from_json_roundtrip(tmp_path):
    p = tmp_path / "mini.json"
    p.write_text(json.dumps(_mini_dataset()), encoding="utf-8")
    ds = EvalDataset.from_json(p)
    assert len(ds.samples) == 4
    assert set(ds.resumes.keys()) == {1, 2, 3, 4}
    # split 过滤
    assert len(ds.by_split("tuning")) == 2
    assert len(ds.by_split("eval")) == 2
    # 类别过滤
    fc = ds.filter_categories(["factual", "reasoning"])
    assert {s.category for s in fc.samples} == {"factual", "reasoning"}


def test_validate_errors():
    raw = _mini_dataset()
    # 删掉一个简历 → resume_id 不匹配
    del raw["resumes"]["3"]
    # 直接构造（绕过 from_dict 的自动 raise），手动测 validate()
    ds = EvalDataset(
        meta=raw.get("meta", {}),
        resumes={int(k): v for k, v in raw.get("resumes", {}).items()},
        samples=[TestSample.from_dict(s) for s in raw.get("samples", [])],
    )
    errs = ds.validate()
    assert any("resume_id=3" in e for e in errs)

    # 类别不足 4
    raw2 = _mini_dataset()
    for s in raw2["samples"]:
        s["category"] = "factual"
    ds2 = EvalDataset(
        meta=raw2.get("meta", {}),
        resumes={int(k): v for k, v in raw2.get("resumes", {}).items()},
        samples=[TestSample.from_dict(s) for s in raw2.get("samples", [])],
    )
    errs2 = ds2.validate()
    assert any("category" in e for e in errs2)


def test_judge_result_composite_math():
    jr = JudgeResult(
        faithfulness=1.0, completeness=0.0, hallucination_score=0.0,
        reject_correctness=0.0, rationale="r", model="m",
    )
    # 0.35*1 + 0.35*0 + 0.15*1 + 0.15*0 = 0.5
    assert abs(jr.composite - 0.5) < 1e-9
    assert jr.needs_reflexion is True  # < 0.6

    jr2 = JudgeResult(1.0, 1.0, 0.0, 1.0, "r", "m")
    assert abs(jr2.composite - 1.0) < 1e-9
    assert jr2.needs_reflexion is False


def test_refused_property():
    from eval.protocol import ExecutorResult

    assert ExecutorResult(answer="抱歉没找到", sources=[]).refused is True
    assert ExecutorResult(answer="有相关信息", sources=[{"text": "x"}]).refused is False
    assert ExecutorResult(answer="答案", sources=[]).refused is True


def test_testsample_from_dict_defaults():
    s = TestSample.from_dict({"id": "x", "resume_id": 1, "category": "c", "question": "q?"})
    assert s.should_answer is True
    assert s.split == "tuning"
    assert s.asker == "hr"
