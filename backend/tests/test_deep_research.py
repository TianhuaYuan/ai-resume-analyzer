from services.agentic_rag.deep_research import ResearchTask, run_research


def test_deep_research_is_bounded_and_typed():
    report = run_research(ResearchTask("t1", "compare role fit"))
    assert report.status == "complete"
    assert {f.agent for f in report.findings} == {"ResumeEvidenceAgent", "JobResearchAgent", "RiskVerifierAgent"}
    assert len(report.trace) <= 4


def test_high_risk_requires_human_gate():
    report = run_research(ResearchTask("t2", "unsafe request", risk="high"))
    assert report.status == "needs_human"
    assert any(x["event"] == "human_gate" for x in report.trace)
