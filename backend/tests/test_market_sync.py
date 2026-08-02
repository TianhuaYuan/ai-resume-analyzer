"""市场数据同步管线测试：幂等 upsert / 变更重索引 / 过期标记 / 归一化 / 双形态加载。"""

import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock, patch

from models.market_asset import MarketAsset
from services import market_sync_service as mss


def _job_record(**over):
    r = {
        "id": "job-1",
        "title": "算法工程师",
        "companyName": "测试公司",
        "company": {"shortName": "测试", "name": "测试公司"},
        "jobType": "CAMPUS",
        "description": "负责推荐算法与排序系统",
        "requirements": "熟悉 Python / PyTorch",
        "salaryDisplay": "20-40K",
        "deadline": "2026-12-31 00:00:00",
    }
    r.update(over)
    return r


def _fanwen_record(**over):
    r = {
        "id": 123,
        "title": "嵌入式开发工程师简历范文",
        "targetJob": "嵌入式开发工程师",
        "category": "技术",
        "summary": "三年嵌入式开发经验，熟悉 Linux",
        "work": "某科技公司实习\n2024-2025",
    }
    r.update(over)
    return r


@pytest.mark.asyncio
async def test_sync_creates_assets(db_session):
    """新资产插入 + eager 索引，indexed_hash == content_hash。"""
    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)) as mock_index, \
         patch.object(mss, "_load_source_json", return_value=[_job_record()]):
        stats = await mss.sync_market(db_session, source=mss.SOURCE_UPCV)

    assert stats.created == 1
    assert stats.indexed == 1
    assert stats.errors == []
    mock_index.assert_awaited_once()
    row = (await db_session.execute(select(MarketAsset))).scalar_one()
    assert row.source == mss.SOURCE_UPCV
    assert row.asset_type == "job"
    assert row.job_type == mss.JOB_TYPE_CAMPUS
    assert row.indexed_hash == row.content_hash
    assert row.index_version == 1
    assert row.is_expired is False


@pytest.mark.asyncio
async def test_sync_idempotent(db_session):
    """同一数据跑两次：第二次 unchanged 全量、index_asset 只调一次。"""
    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)) as mock_index, \
         patch.object(mss, "_load_source_json", return_value=[_job_record()]):
        stats1 = await mss.sync_market(db_session, source=mss.SOURCE_UPCV)
        stats2 = await mss.sync_market(db_session, source=mss.SOURCE_UPCV)

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
         patch.object(mss, "_load_source_json", return_value=[_job_record()]):
        await mss.sync_market(db_session, source=mss.SOURCE_UPCV)

    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)) as mock_index2, \
         patch.object(mss, "_load_source_json",
                      return_value=[_job_record(description="改为大模型方向")]):
        stats2 = await mss.sync_market(db_session, source=mss.SOURCE_UPCV)

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
         patch.object(mss, "_load_source_json",
                      return_value=[_job_record(deadline="2020-01-01 00:00:00")]):
        stats = await mss.sync_market(db_session, source=mss.SOURCE_UPCV)

    assert stats.expired == 1
    row = (await db_session.execute(select(MarketAsset))).scalar_one()
    assert row.is_expired is True


@pytest.mark.asyncio
async def test_deadline_none_not_expired(db_session):
    """无 deadline → 不过期。"""
    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)), \
         patch.object(mss, "_load_source_json",
                      return_value=[_job_record(deadline=None)]):
        await mss.sync_market(db_session, source=mss.SOURCE_UPCV)

    row = (await db_session.execute(select(MarketAsset))).scalar_one()
    assert row.is_expired is False


@pytest.mark.asyncio
async def test_fanwen_normalized_to_sample(db_session):
    """范文归一化为 sample 资产，targetJob → position。"""
    with patch.object(mss, "index_asset", new=AsyncMock(return_value=5)), \
         patch.object(mss, "_load_source_json", return_value=[_fanwen_record()]):
        stats = await mss.sync_market(db_session, source=mss.SOURCE_SAMPLE)

    assert stats.created == 1
    row = (await db_session.execute(select(MarketAsset))).scalar_one()
    assert row.asset_type == "sample"
    assert row.job_type is None
    assert row.position == "嵌入式开发工程师"
    assert row.external_id == "123"
    assert row.payload["target_position"] == "嵌入式开发工程师"
    assert "工作经历" in row.content


def test_load_source_json_both_shapes():
    """_load_source_json 兼容顶层 list 与 {"data":[...]} 两种形态。"""
    # upcv_jobs.json 是 dict {"data":[...]}；campus_recruitment.json 是 list
    upcv = mss._load_source_json(mss.SOURCE_UPCV)
    campus = mss._load_source_json(mss.SOURCE_CAMPUS)
    assert isinstance(upcv, list) and len(upcv) > 0
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


def test_normalize_guide():
    """攻略归一化：summary → content，url/article_id → payload，has_fulltext=False。"""
    n = mss._normalize_guide({
        "article_id": "5836", "title": "攻略标题", "summary": "攻略摘要",
        "url": "https://x.com/5836.html", "date": "2026/8/2",
    })
    assert n.asset_type == "guide"
    assert n.external_id == "5836"
    assert n.content == "攻略摘要"
    assert n.payload["url"] == "https://x.com/5836.html"
    assert n.payload["has_fulltext"] is False


def test_load_articles_shape():
    """all_articles.json 顶层 {"articles":[...]} 形态能加载。"""
    records = mss._load_source_json(mss.SOURCE_GUIDE)
    assert isinstance(records, list) and len(records) > 0
    assert "title" in records[0]
