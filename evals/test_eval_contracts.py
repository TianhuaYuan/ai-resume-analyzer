import json
from pathlib import Path

from schema import validate_case


def test_dataset_contract_has_required_risk_guards():
    path = Path(__file__).parent / "datasets" / "cases.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(not validate_case(case) for case in cases)
    assert sum(case["expected"]["must_refuse_unsafe"] for case in cases) == 24
    assert sum(case["expected"]["must_state_uncertainty"] for case in cases) == 24
