"""Run admission, cancellation and terminal-state persistence.

Each operation opens its own short DB session. A streaming request must never
hold the request session while it waits on an LLM or an approval decision.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.database import AsyncSessionLocal
from core.redis_client import get_redis
from models.agent_run import AgentRun

logger = logging.getLogger(__name__)

ACTIVE_TTL = 30 * 60
CANCEL_TTL = ACTIVE_TTL
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"awaiting_approval", "succeeded", "failed", "cancelled"}),
    "awaiting_approval": frozenset({"running", "failed", "cancelled"}),
}


class RunConflictError(RuntimeError):
    """Another run owns same user/resume/conversation scope."""


class RunStateError(RuntimeError):
    """Invalid or stale lifecycle transition."""


@dataclass(frozen=True)
class ActiveOwner:
    run_id: str
    turn_id: str
    owner_token: str
    user_id: int
    resume_id: int
    conversation_id: int | None


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    turn_id: str
    owner_token: str
    active_key: str
    cancel_key: str
    user_id: int
    resume_id: int
    conversation_id: int | None


def scope_key(user_id: int, resume_id: int, conversation_id: int | None) -> str:
    return f"react:active:{user_id}:{resume_id}:{conversation_id if conversation_id is not None else 'all'}"


def _meta_key(active_key: str) -> str:
    return f"{active_key}:meta"


def cancel_key_for(run_id: str) -> str:
    return f"react:cancel:{run_id}"


def injection_key_for(owner: ActiveOwner | RunHandle) -> str:
    """Queue key includes turn; messages cannot bleed into next execution."""
    conv = owner.conversation_id if owner.conversation_id is not None else "all"
    return f"react:inject:{owner.user_id}:{owner.resume_id}:{conv}:{owner.turn_id}"


async def _cas_release(redis: Any, key: str, token: str) -> bool:
    try:
        # Uppercase Redis commands are also understood by the in-memory test
        # adapter, keeping CAS release semantics identical across backends.
        script = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"
        if hasattr(redis, "eval"):
            return bool(await redis.eval(script, 1, key, token))
        current = await redis.get(key)
        if current == token:
            return bool(await redis.delete(key))
    except Exception:
        logger.warning("failed to CAS release run owner key", exc_info=True)
    return False


class RunLifecycle:
    """Repository for ownership and run state. Every DB operation is isolated."""

    def __init__(self, session_factory=None, redis_factory=get_redis, *, persist=True):
        # Resolve the default lazily.  Besides making the dependency explicit,
        # this lets application/test bootstraps inject the correct database
        # engine before a stream starts (the old default was bound at import
        # time and could point at a different SQLite file in tests).
        self.session_factory = session_factory or AsyncSessionLocal
        self.redis_factory = redis_factory
        self.persist = persist

    async def start(
        self,
        *,
        user_id: int,
        resume_id: int,
        conversation_id: int | None,
        turn_id: str,
        route: str = "agent",
    ) -> RunHandle:
        active_key = scope_key(user_id, resume_id, conversation_id)
        owner_token = uuid.uuid4().hex
        redis = await self.redis_factory()
        claimed = await redis.set(active_key, owner_token, nx=True, ex=ACTIVE_TTL)
        if not claimed:
            raise RunConflictError(active_key)

        run_id = uuid.uuid4().hex
        handle = RunHandle(
            run_id=run_id,
            turn_id=turn_id,
            owner_token=owner_token,
            active_key=active_key,
            cancel_key=cancel_key_for(run_id),
            user_id=user_id,
            resume_id=resume_id,
            conversation_id=conversation_id,
        )
        try:
            if self.persist:
                async with self.session_factory() as session:
                    session.add(
                        AgentRun(
                            run_id=run_id,
                            turn_id=turn_id,
                            user_id=user_id,
                            resume_id=resume_id,
                            conversation_id=conversation_id,
                            route=route,
                            status="created",
                            started_at=datetime.now(timezone.utc),
                        )
                    )
                    await session.commit()
                    await self._transition_in_session(session, run_id, "running")
                    await session.commit()
            await redis.set(
                _meta_key(active_key),
                json.dumps(
                    {
                        "run_id": run_id,
                        "turn_id": turn_id,
                        "owner_token": owner_token,
                        "user_id": user_id,
                        "resume_id": resume_id,
                        "conversation_id": conversation_id,
                    },
                    separators=(",", ":"),
                ),
                ex=ACTIVE_TTL,
            )
            return handle
        except Exception:
            await _cas_release(redis, active_key, owner_token)
            try:
                await redis.delete(_meta_key(active_key))
            except Exception:
                pass
            raise

    async def _transition_in_session(
        self, session, run_id: str, target: str, *, degraded: bool | None = None,
        usage: dict | None = None, error_code: str | None = None,
    ) -> AgentRun:
        run = await session.get(AgentRun, run_id)
        if run is None:
            raise RunStateError(f"run not found: {run_id}")
        current = run.status
        if current in TERMINAL_STATUSES:
            if current != target:
                raise RunStateError(f"terminal run cannot transition: {current}->{target}")
            return run
        if target not in TRANSITIONS.get(current, frozenset()):
            raise RunStateError(f"invalid run transition: {current}->{target}")
        run.status = target
        if degraded is not None:
            run.degraded = degraded
        if usage is not None:
            run.usage = usage
        if error_code is not None:
            run.error_code = error_code
        if target in TERMINAL_STATUSES:
            run.finished_at = datetime.now(timezone.utc)
        return run

    async def transition(self, run_id: str, target: str, **kwargs) -> AgentRun | None:
        if not self.persist:
            return None
        async with self.session_factory() as session:
            run = await self._transition_in_session(session, run_id, target, **kwargs)
            await session.commit()
            return run

    async def get(self, run_id: str) -> AgentRun | None:
        if not self.persist:
            return None
        async with self.session_factory() as session:
            return await session.get(AgentRun, run_id)

    async def request_cancel(self, run_id: str) -> bool:
        run = await self.get(run_id)
        if run is None or run.status in TERMINAL_STATUSES:
            return False
        redis = await self.redis_factory()
        await redis.set(cancel_key_for(run_id), "1", ex=CANCEL_TTL)
        return True

    async def is_cancel_requested(self, run_id: str) -> bool:
        redis = await self.redis_factory()
        return bool(await redis.get(cancel_key_for(run_id)))

    async def active_owner(
        self, user_id: int, resume_id: int, conversation_id: int | None
    ) -> ActiveOwner | None:
        redis = await self.redis_factory()
        active_key = scope_key(user_id, resume_id, conversation_id)
        raw = await redis.get(_meta_key(active_key))
        if raw:
            try:
                payload = json.loads(raw)
                return ActiveOwner(**payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.warning("invalid active run metadata: key=%s", active_key)
        # Legacy owner key may have been created by a pre-v2 request. Do not
        # enqueue into it; expose only enough metadata for a compatible 409.
        raw_owner = await redis.get(active_key)
        if raw_owner:
            if isinstance(raw_owner, bytes):
                raw_owner = raw_owner.decode("utf-8", errors="ignore")
            return ActiveOwner(
                run_id="",
                turn_id=str(raw_owner),
                owner_token=str(raw_owner),
                user_id=user_id,
                resume_id=resume_id,
                conversation_id=conversation_id,
            )
        return None

    async def release(self, handle: RunHandle) -> None:
        redis = await self.redis_factory()
        released = await _cas_release(redis, handle.active_key, handle.owner_token)
        # Only the owner that successfully released the lease may remove its
        # metadata. A late cleanup from an old turn must not delete the new
        # owner's metadata after a lease handoff.
        if released:
            try:
                await redis.delete(_meta_key(handle.active_key))
            except Exception:
                pass
        try:
            await redis.delete(handle.cancel_key)
        except Exception:
            pass

    async def finalize(
        self, handle: RunHandle, *, status: str = "failed", degraded: bool = False,
        usage: dict | None = None, error_code: str | None = None,
    ) -> AgentRun | None:
        try:
            run = await self.transition(
                handle.run_id, status, degraded=degraded, usage=usage, error_code=error_code
            )
        finally:
            await self.release(handle)
        return run


__all__ = [
    "ActiveOwner",
    "RunConflictError",
    "RunHandle",
    "RunLifecycle",
    "RunStateError",
    "TERMINAL_STATUSES",
    "cancel_key_for",
    "injection_key_for",
    "scope_key",
]
