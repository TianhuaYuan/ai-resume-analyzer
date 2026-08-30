"""Bounded, typed multi-agent orchestration for career deep research.

The module intentionally keeps agents as pure functions around a shared state;
an LLM adapter can be plugged in later without introducing free-form agent chat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ResearchTask:
    task_id: str
    prompt: str
    risk: Literal["low", "medium", "high"] = "low"


@dataclass(frozen=True)
class ResearchFinding:
    agent: str
    claim: str
    evidence: str
    confidence: float
    source_priority: int = 0


@dataclass(frozen=True)
class ConflictRecord:
    claim: str
    candidates: tuple[str, ...]
    resolution: str
    reason: str


@dataclass
class ResearchReport:
    task_id: str
    findings: list[ResearchFinding] = field(default_factory=list)
    conflicts: list[ConflictRecord] = field(default_factory=list)
    status: Literal["complete", "degraded", "needs_human"] = "complete"
    trace: list[dict] = field(default_factory=list)


def _resume_agent(task: ResearchTask) -> ResearchFinding:
    return ResearchFinding("ResumeEvidenceAgent", "resume_evidence_checked", "resume_source", .8, 2)


def _job_agent(task: ResearchTask) -> ResearchFinding:
    return ResearchFinding("JobResearchAgent", "job_requirements_checked", "job_source", .8, 1)


def _risk_agent(task: ResearchTask, findings: list[ResearchFinding]) -> ResearchFinding:
    return ResearchFinding("RiskVerifierAgent", "risk_reviewed", "cross_check", .9 if task.risk != "high" else .6, 3)


def run_research(task: ResearchTask, *, max_agents: int = 3, max_rounds: int = 2) -> ResearchReport:
    if max_agents != 3 or max_rounds != 2:
        raise ValueError("policy requires max_agents=3 and max_rounds=2")
    report = ResearchReport(task.task_id)
    report.trace.append({"event": "dispatch", "agents": 3, "round": 1})
    report.findings.extend([_resume_agent(task), _job_agent(task)])
    report.trace.append({"event": "parallel_findings", "count": 2, "round": 1})
    report.findings.append(_risk_agent(task, report.findings))
    report.trace.append({"event": "arbitration", "round": 2})
    if task.risk == "high":
        report.status = "needs_human"
        report.trace.append({"event": "human_gate", "reason": "high_risk"})
    return report

