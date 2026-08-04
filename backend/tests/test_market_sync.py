"""市场数据同步管线测试：幂等 upsert / 变更重索引 / 过期标记 / 归一化 / 岗位数据加载。"""

import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock, patch

from models.market_asset import MarketAsset
from services import market_sync_service as mss


def _job_record(**over):
    r = {
        "_source": "upcv_jobs",
        "id": "job-1",
        "title": "算法工程师",
        "companyName": "测试公司",
        "company": {"shortName": "测试", "name": "测试公司"},
        "jobType": "CAMPUS",
        "description": "负责推荐算法与排序系统",
        "requirements": "熟悉 Python / PyTorch",
        "salaryDisplay": "20-40K",
        "deadline": "2026-12-31 00:00:00",
        "detailUrl": "https://x.com/job-1",
        "publishedAt": "2026-08-01T10:00:00Z",
    }
    r.update(over)
    return r


@pytest.mark.asyncio
async def test_sync_creates_assets(db_session):
    """新资产插入 + eager 索引，indexed_hash == content_hash。"""
    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)) as mock_index, \
         patch.object(mss, "_load_market_records", return_value=[_job_record()]):
        stats = await mss.sync_market(db_session, file="jobs_campus")

    assert stats.created == 1
    assert stats.indexed == 1
    assert stats.errors == []
    mock_index.assert_awaited_once()
    row = (await db_session.execute(select(MarketAsset))).scalar_one()
    assert row.source == mss.SOURCE_UPCV
    assert row.job_type == mss.JOB_TYPE_CAMPUS
    assert row.apply_url == "https://x.com/job-1"
    assert row.published_at is not None
    assert row.indexed_hash == row.content_hash
    assert row.index_version == 1
    assert row.is_expired is False


@pytest.mark.asyncio
async def test_sync_idempotent(db_session):
    """同一数据跑两次：第二次 unchanged 全量、index_asset 只调一次。"""
    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)) as mock_index, \
         patch.object(mss, "_load_market_records", return_value=[_job_record()]):
        stats1 = await mss.sync_market(db_session, file="jobs_campus")
        stats2 = await mss.sync_market(db_session, file="jobs_campus")

    assert stats1.created == 1
    assert stats2.created == 0
    assert stats2.updated == 0
    assert stats2.unchanged == 1
    assert stats2.indexed == 0
    assert mock_index.await_count == 1  # 幂等：只索引一次
    row = (await db_session.execute(select(MarketAsset))).scalar_one()
    assert row.index_version == 1


@pytest.mark.asyncio
async def test_sync_updates_on_content_change(db_session):
    """内容变了 → updated + 重新索引。"""
    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)) as mock_index, \
         patch.object(mss, "_load_market_records", return_value=[_job_record()]):
        await mss.sync_market(db_session, file="jobs_campus")

    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)) as mock_index2, \
         patch.object(mss, "_load_market_records",
                      return_value=[_job_record(description="改为大模型方向")]):
        stats2 = await mss.sync_market(db_session, file="jobs_campus")

    assert stats2.updated == 1
    assert stats2.indexed == 1
    assert mock_index2.await_count == 1
    row = (await db_session.execute(select(MarketAsset))).scalar_one()
    assert "大模型" in row.content
    assert row.index_version == 2


@pytest.mark.asyncio
async def test_expired_marking(db_session):
    """deadline 已过 → is_expired=True。"""
    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)), \
         patch.object(mss, "_load_market_records",
                      return_value=[_job_record(deadline="2020-01-01 00:00:00")]):
        stats = await mss.sync_market(db_session, file="jobs_campus")

    assert stats.expired == 1
    row = (await db_session.execute(select(MarketAsset))).scalar_one()
    assert row.is_expired is True


@pytest.mark.asyncio
async def test_deadline_none_not_expired(db_session):
    """无 deadline → 不过期。"""
    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)), \
         patch.object(mss, "_load_market_records",
                      return_value=[_job_record(deadline=None)]):
        await mss.sync_market(db_session, file="jobs_campus")

    row = (await db_session.execute(select(MarketAsset))).scalar_one()
    assert row.is_expired is False


def test_load_market_records():
    """岗位分类 JSON 的 records 数组能加载。"""
    campus = mss._load_market_records("jobs_campus")
    assert isinstance(campus, list) and len(campus) > 0


def test_resolve_job_type_mapping():
    """跨源 job_type 标准化映射。"""
    assert mss._resolve_job_type({"jobType": "CAMPUS"}, mss.SOURCE_UPCV) == "campus"
    assert mss._resolve_job_type({"jobType": "INTERNSHIP"}, mss.SOURCE_UPCV) == "intern"
    assert mss._resolve_job_type({"jobType": "X"}, mss.SOURCE_UPCV) == "social"
    assert mss._resolve_job_type({"recruit_type": "应届生"}, mss.SOURCE_ALLJOBS) == "campus"
    assert mss._resolve_job_type({"recruit_label": "暑期实习"}, mss.SOURCE_ALLJOBS) == "intern"
    assert mss._resolve_job_type({"infoType": "内推"}, mss.SOURCE_CAMPUS) == "social"
    assert mss._resolve_job_type({"infoType": "校招"}, mss.SOURCE_CAMPUS) == "campus"
    assert mss._resolve_job_type({}, mss.SOURCE_REFERRAL) == "social"
