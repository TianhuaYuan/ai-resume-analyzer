"""Focused ownership/lifecycle contract tests (no full suite)."""

import pytest

from core.redis_client import InMemoryRedis
from models.agent_run import AgentRun
from services.react_agent.run_lifecycle import (
    RunConflictError,
    RunLifecycle,
    RunStateError,
    scope_key,
)


class _Store:
    def __init__(self):
        self.rows: dict[str, AgentRun] = {}


class _Session:
    def __init__(self, store):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, row):
        self.store.rows[row.run_id] = row

    async def get(self, model, key):
        return self.store.rows.get(key)

    async def commit(self):
        return None


class _Factory:
    def __init__(self, store):
        self.store = store

    def __call__(self):
        return _Session(self.store)


@pytest.fixture
def lifecycle():
    store = _Store()
    redis = InMemoryRedis()
    return RunLifecycle(_Factory(store), lambda: _return(redis)), redis, store


async def _return(value):
    return value


@pytest.mark.asyncio
async def test_same_scope_has_one_owner_and_old_release_cannot_delete_new_owner(lifecycle):
    lc, redis, _ = lifecycle
    first = await lc.start(user_id=1, resume_id=2, conversation_id=3, turn_id="turn-a")
    with pytest.raises(RunConflictError):
        await lc.start(user_id=1, resume_id=2, conversation_id=3, turn_id="turn-b")

    # Simulate owner expiry/replacement by a new owner token.
    await redis.set(scope_key(1, 2, 3), "new-token", ex=100)
    await lc.release(first)
    assert await redis.get(scope_key(1, 2, 3)) == "new-token"


@pytest.mark.asyncio
async def test_different_conversations_can_run_in_parallel(lifecycle):
    lc, _, _ = lifecycle
    first = await lc.start(user_id=1, resume_id=2, conversation_id=3, turn_id="turn-a")
    second = await lc.start(user_id=1, resume_id=2, conversation_id=4, turn_id="turn-b")
    assert first.run_id != second.run_id


@pytest.mark.asyncio
async def test_cancel_intent_and_terminal_state_are_persisted(lifecycle):
    lc, _, store = lifecycle
    handle = await lc.start(user_id=1, resume_id=2, conversation_id=None, turn_id="turn-a")
    assert await lc.request_cancel(handle.run_id)
    assert await lc.is_cancel_requested(handle.run_id)
    await lc.transition(handle.run_id, "cancelled", error_code="user_cancelled")
    assert store.rows[handle.run_id].status == "cancelled"
    with pytest.raises(RunStateError):
        await lc.transition(handle.run_id, "running")
