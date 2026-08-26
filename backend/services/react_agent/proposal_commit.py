"""Proposal-first commit service for Agent-produced resume mutations."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.database import AsyncSessionLocal
from models.agent_proposal import AgentProposal
from models.resume import Resume
from models.resume_module import ResumeModule
from services.resume_module_mutation import (
    ResumeModuleConflictError,
    load_resume_modules_for_mutation,
    lock_resume_for_module_mutation,
)


class ProposalError(RuntimeError):
    pass


class ProposalConflictError(ProposalError):
    pass


class ProposalStaleError(ProposalError):
    pass


@dataclass(frozen=True)
class ProposalDraft:
    proposal_id: str
    user_id: int
    resume_id: int
    base_revision: int
    content_hash: str
    status: str
    idempotency_key: str


def _canonical_hash(operations: list[dict], rationale: str) -> str:
    payload = json.dumps(
        {"operations": operations, "rationale": rationale},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_operations(operations: list[dict]) -> None:
    if not isinstance(operations, list) or not operations:
        raise ProposalError("proposal operations cannot be empty")
    seen: set[str] = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise ProposalError("proposal operation must be an object")
        module_type = operation.get("module_type")
        content = operation.get("content")
        if not isinstance(module_type, str) or not module_type.strip():
            raise ProposalError("proposal module_type is required")
        if module_type in seen:
            raise ProposalError(f"duplicate proposal module_type: {module_type}")
        if not isinstance(content, dict) or not content:
            raise ProposalError(f"proposal content is invalid: {module_type}")
        source = operation.get("source", "unknown")
        if source not in {"fact", "inferred", "mixed", "unknown"}:
            raise ProposalError(f"proposal source is invalid: {source}")
        seen.add(module_type)


class ProposalCommitService:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory or AsyncSessionLocal

    async def create(
        self,
        *,
        user_id: int,
        resume_id: int,
        call_id: str,
        operations: list[dict],
        rationale: str = "",
        evidence: list[dict] | None = None,
        idempotency_key: str | None = None,
        run_id: str | None = None,
    ) -> ProposalDraft:
        _validate_operations(operations)
        idempotency_key = idempotency_key or uuid.uuid4().hex
        content_hash = _canonical_hash(operations, rationale)
        async with self.session_factory() as session:
            existing = await session.scalar(
                select(AgentProposal).where(AgentProposal.idempotency_key == idempotency_key)
            )
            if existing is not None:
                if existing.content_hash != content_hash or existing.user_id != user_id:
                    raise ProposalConflictError("idempotency key is bound to another proposal")
                return ProposalDraft(existing.proposal_id, existing.user_id, existing.resume_id, existing.base_revision, existing.content_hash, existing.status, existing.idempotency_key)
            resume = await session.scalar(
                select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
            )
            if resume is None:
                raise ProposalError("resume not found or not owned by user")
            proposal_id = uuid.uuid4().hex
            row = AgentProposal(
                proposal_id=proposal_id,
                run_id=run_id,
                call_id=call_id,
                user_id=user_id,
                resume_id=resume_id,
                base_revision=resume.module_revision,
                operations=operations,
                evidence=list(evidence or []),
                rationale=rationale,
                content_hash=content_hash,
                idempotency_key=idempotency_key,
                status="awaiting_approval",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ProposalConflictError("proposal idempotency conflict") from exc
            return ProposalDraft(proposal_id, user_id, resume_id, row.base_revision, content_hash, row.status, idempotency_key)

    async def decide(self, *, proposal_id: str, user_id: int, approved: bool) -> ProposalDraft:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AgentProposal).where(
                    AgentProposal.proposal_id == proposal_id,
                    AgentProposal.user_id == user_id,
                ).with_for_update()
            )
            if row is None:
                raise ProposalError("proposal not found")
            if row.status in {"applied", "stale", "rejected"}:
                return ProposalDraft(row.proposal_id, row.user_id, row.resume_id, row.base_revision, row.content_hash, row.status, row.idempotency_key)
            row.status = "approved" if approved else "rejected"
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return ProposalDraft(row.proposal_id, row.user_id, row.resume_id, row.base_revision, row.content_hash, row.status, row.idempotency_key)

    async def apply(self, *, proposal_id: str, user_id: int, idempotency_key: str) -> dict:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AgentProposal).where(
                    AgentProposal.proposal_id == proposal_id,
                    AgentProposal.user_id == user_id,
                ).with_for_update()
            )
            if row is None:
                raise ProposalError("proposal not found")
            if row.idempotency_key != idempotency_key:
                raise ProposalConflictError("proposal idempotency key mismatch")
            if row.status == "applied":
                return {"proposal_id": row.proposal_id, "status": row.status, "revision": row.applied_revision}
            if row.status != "approved":
                raise ProposalError(f"proposal is not approved: {row.status}")
            if _canonical_hash(row.operations, row.rationale) != row.content_hash:
                raise ProposalConflictError("proposal content hash mismatch")
            _validate_operations(row.operations)
            try:
                resume = await lock_resume_for_module_mutation(
                    session, user_id, row.resume_id, expected_revision=row.base_revision
                )
            except ResumeModuleConflictError as exc:
                row.status = "stale"
                await session.commit()
                raise ProposalStaleError(str(exc)) from exc
            if resume is None:
                raise ProposalError("resume not found or not owned by user")
            current = await load_resume_modules_for_mutation(session, row.resume_id)
            current_map = {module.module_type: module for module in current}
            for operation in row.operations:
                module_type = operation["module_type"]
                module = current_map.get(module_type)
                if module is None:
                    module = ResumeModule(
                        resume_id=row.resume_id,
                        module_type=module_type,
                        content=operation["content"],
                        sort_order=int(operation.get("sort_order", len(current_map))),
                        source=operation.get("source", "unknown"),
                    )
                    session.add(module)
                else:
                    module.content = operation["content"]
                    module.source = operation.get("source", "unknown")
                    if "sort_order" in operation:
                        module.sort_order = int(operation["sort_order"])
            # New modules are still pending in SQLAlchemy's unit of work.
            # Flush before rebuilding the derived text so the current-read
            # query includes both inserts and updates in this transaction.
            await session.flush()
            # Keep the derived resume representation in the same transaction
            # as the module operations.  Proposal apply must be observable by
            # both the editor and retrieval pipeline immediately after commit.
            from services.resume_builder import _merge_modules_to_text
            from services.resume_service import set_resume_status

            refreshed_modules = await load_resume_modules_for_mutation(session, row.resume_id)
            merged = _merge_modules_to_text(list(refreshed_modules))
            resume.parsed_text = merged
            resume.content_hash = hashlib.sha256(merged.encode("utf-8")).hexdigest()
            resume.updated_at = datetime.now(timezone.utc)
            if resume.status == "ready":
                await set_resume_status(session, resume, "draft", reason="Agent Proposal 已应用")
            row.status = "applied"
            row.applied_revision = resume.module_revision
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return {"proposal_id": row.proposal_id, "status": row.status, "revision": row.applied_revision}
