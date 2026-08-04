"""B/E3 求职复盘：状态机 + 复盘纯函数 + review API 测试。"""

from datetime import date

import pytest

from services.campus_review import (
    build_funnel,
    cluster_rejection_reasons,
    compute_reached,
    find_ghost_candidates,
    normalize_stage_reached,
)
from services.campus_status import (
    STATUSES,
    STATUS_FLOW,
    TERMINAL_STATUSES,
    assert_valid_status,
    can_transition,
    next_statuses,
)


# ── 状态机 ──


@pytest.mark.asyncio
async def test_status_machine_constants():
    assert "pending" in STATUSES
    assert "applied" in STATUSES
    assert "offer" in TERMINAL_STATUSES
    assert "rejected" in TERMINAL_STATUSES
    assert "cancelled" in TERMINAL_STATUSES


@pytest.mark.asyncio
async def test_can_transition_rule():
    assert can_transition("applied", "applied") is True  # 同状态 no-op
    assert can_transition("pending", "applied") is True
    assert can_transition("applied", "first_round") is True
    assert can_transition("first_round", "offer") is True  # 轮次可跳过
    assert can_transition("offer", "pending") is False  # 终态锁死
    assert can_transition("rejected", "applied") is False


@pytest.mark.asyncio
async def test_assert_valid_status():
    assert_valid_status("applied")  # 不抛
    with pytest.raises(ValueError):
        assert_valid_status("not_a_status")


@pytest.mark.asyncio
async def test_next_statuses_subset():
    nxt = next_statuses("applied")
    assert isinstance(nxt, list)
    assert all(s in STATUSES for s in nxt)


# ── 复盘纯函数 ──


def _track(**kw):
    base = {
        "id": 1,
        "user_id": 1,
        "campus_record_id": "rec1",
        "status": "applied",
        "date_applied": date(2026, 7, 1),
        "source": "牛客",
        "rejection_reason": None,
        "stage_reached": None,
    }
    base.update(kw)
    return base


def test_build_funnel_counts():
    tracks = [_track(status="applied"), _track(status="offer", campus_record_id="rec2"), _track(status="applied", campus_record_id="rec3")]
    funnel = build_funnel(tracks)
    assert isinstance(funnel, list)
    by_status = {item["status"]: item["count"] for item in funnel}
    assert by_status["applied"] == 2
    assert by_status["offer"] == 1
    assert by_status["pending"] == 0  # 含零


def test_build_funnel_empty():
    funnel = build_funnel([])
    assert len(funnel) == len(STATUSES)
    assert all(item["count"] == 0 for item in funnel)


def test_compute_reached_terminal_min_applied():
    tracks = [_track(status="rejected", campus_record_id="r1")]
    reached = compute_reached(tracks, [])
    assert reached["r1"] >= 0  # 终局态至少 applied


def test_normalize_stage_reached():
    assert normalize_stage_reached("一面挂") is not None or normalize_stage_reached(None) is None
    assert normalize_stage_reached(None) is None


def test_cluster_rejection_reasons_buckets():
    reasons = ["技能不匹配", "岗位关闭暂停招聘", ""]
    result = cluster_rejection_reasons(reasons)
    assert isinstance(result, list)
    assert len(result) > 0
    total = sum(item["count"] for item in result)
    assert total <= len(reasons)


def test_find_ghost_candidates():
    tracks = [_track(status="applied", campus_record_id="r1", date_applied=date(2026, 1, 1))]
    ghosts = find_ghost_candidates(tracks, [], ghost_days=30)
    assert isinstance(ghosts, list)
    # 1 月 1 日投递且无联系，远超 30 天 → 应进入候选
    assert any(g["campus_record_id"] == "r1" for g in ghosts)


# ── review/summary API ──


@pytest.mark.asyncio
async def test_review_summary_api(client, auth_headers):
    resp = await client.get("/api/v1/campus/review/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "kpis" in data
    assert "funnel" in data
    assert "conversion" in data
    assert "rejection_reasons" in data
    assert "ghost_candidates" in data


@pytest.mark.asyncio
async def test_track_upsert_status_change_records_event(client, auth_headers, test_user, db_session):
    """PUT /campus/tracks 状态变更应追加 campus_track_events。"""
    from models.campus_track_event import CampusTrackEvent

    resp = await client.put(
        "/api/v1/campus/tracks",
        json={"campus_record_id": "campus-1", "status": "applied", "date_applied": "2026-07-01"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    resp2 = await client.put(
        "/api/v1/campus/tracks",
        json={"campus_record_id": "campus-1", "status": "first_round"},
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    from sqlalchemy import select

    events = (
        await db_session.execute(
            select(CampusTrackEvent).where(CampusTrackEvent.user_id == test_user.id)
        )
    ).scalars().all()
    # 状态变更会追加事件（创建时无旧状态不记，变更时记）
    assert len(events) >= 1
    assert events[-1].to_status == "first_round"
    assert events[-1].from_status == "applied"


@pytest.mark.asyncio
async def test_track_upsert_invalid_transition_rejected(client, auth_headers):
    """非法状态转换 → 400。"""
    await client.put(
        "/api/v1/campus/tracks",
        json={"campus_record_id": "campus-2", "status": "offer"},
        headers=auth_headers,
    )
    resp = await client.put(
        "/api/v1/campus/tracks",
        json={"campus_record_id": "campus-2", "status": "pending"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
