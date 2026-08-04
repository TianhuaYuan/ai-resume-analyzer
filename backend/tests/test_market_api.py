"""市场数据 API 测试：公开浏览 / 鉴权推荐 / admin 同步 / 分页过滤。"""

import pytest
from unittest.mock import AsyncMock, patch

from core.config import settings
from models.market_asset import MarketAsset


def _make_job(*, id=1, external_id="j1", job_type="campus", company="测试公司",
              title="算法工程师", salary="20-40K", city="北京", deadline=None, content="...",
              is_expired=False, apply_url=None, published_at=None):
    from datetime import datetime, timezone
    return MarketAsset(
        id=id, source="upcv", external_id=external_id,
        job_type=job_type, title=title, company=company, position=title,
        city=city, salary=salary, deadline=deadline, is_expired=is_expired,
        apply_url=apply_url, published_at=published_at,
        content=content, content_hash="abc",
    )


async def _seed_job(db_session, **kw):
    row = _make_job(**kw)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_jobs_public_anonymous(db_session, client):
    """岗位列表公开可匿名访问。"""
    from datetime import datetime, timezone
    await _seed_job(db_session, apply_url="https://x.com/apply", published_at=datetime(2026, 7, 1))
    resp = await client.get("/api/v1/market/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["company"] == "测试公司"
    assert item["job_type"] == "campus"
    assert item["apply_url"] == "https://x.com/apply"
    assert item["published_at"] is not None
    # source 仅内部幂等键，API 不暴露
    assert "source" not in item
    # 列表不含 content 全文
    assert "content" not in item


@pytest.mark.asyncio
async def test_jobs_filter_job_type_and_search(db_session, client):
    """按 job_type 过滤 + 关键词搜索。"""
    await _seed_job(db_session, id=1, job_type="campus", title="算法工程师")
    await _seed_job(db_session, id=2, external_id="j2", job_type="social", title="后端开发")
    await db_session.commit()

    resp = await client.get("/api/v1/market/jobs?job_type=social")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["title"] == "后端开发"

    resp = await client.get("/api/v1/market/jobs?q=算法")
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["title"] == "算法工程师"


@pytest.mark.asyncio
async def test_expired_jobs_excluded(db_session, client):
    """过期岗位不出现在浏览列表。"""
    from datetime import datetime, timezone
    await _seed_job(db_session, id=1, is_expired=True)
    await _seed_job(db_session, id=2, external_id="j2")
    resp = await client.get("/api/v1/market/jobs")
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == 2


@pytest.mark.asyncio
async def test_job_detail_public(db_session, client):
    """岗位详情含 content 全文。"""
    await _seed_job(db_session, content="负责推荐系统全链路")
    resp = await client.get("/api/v1/market/jobs/1")
    assert resp.status_code == 200
    assert "content" in resp.json()
    assert resp.json()["content"] == "负责推荐系统全链路"


@pytest.mark.asyncio
async def test_job_detail_not_found(client):
    resp = await client.get("/api/v1/market/jobs/999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_recommend_requires_auth(client):
    """岗位推荐未登录 → 401。"""
    resp = await client.post("/api/v1/market/recommend", json={"resume_id": 1})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_recommend_authenticated(client, registered_user, auth_headers):
    """登录后推荐返回匹配岗位（mock 推荐服务）。"""
    from services import market_match_service
    fake_items = [{
        "id": 1, "title": "算法工程师", "company": "测试公司", "position": "算法工程师",
        "city": "北京", "salary": "20-40K", "job_type": "campus",
        "score": 85, "matched": ["Python"], "gaps": ["分布式"], "reason": "技能匹配",
    }]
    with patch.object(market_match_service, "recommend_jobs", new=AsyncMock(return_value=fake_items)):
        resp = await client.post(
            "/api/v1/market/recommend",
            json={"resume_id": 1, "top_k": 3},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["score"] == 85
    assert items[0]["matched"] == ["Python"]


@pytest.mark.asyncio
async def test_admin_sync_requires_admin(client, auth_headers):
    """非 admin 调用市场同步 → 403。"""
    resp = await client.post("/api/v1/admin/market/sync", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_sync_success(client, registered_user, auth_headers):
    """admin 触发同步 → 200 + stats（mock 同步避免真实 embedding 与数据文件）。"""
    from api import admin as admin_module
    from services import market_sync_service

    orig_admin_emails = settings.ADMIN_EMAILS
    # 复用 conftest 的普通测试用户，临时把其邮箱加入 admin 白名单（避免重复注册用户）
    settings.ADMIN_EMAILS = registered_user["email"]
    try:
        # 注意：admin.py 是模块顶部 import sync_market，必须 patch api.admin 命名空间的引用
        with patch.object(admin_module, "sync_market",
                          new=AsyncMock(return_value=market_sync_service.MarketSyncStats(
                              total=3, created=3, indexed=3))):
            resp = await client.post("/api/v1/admin/market/sync", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["created"] == 3
    finally:
        settings.ADMIN_EMAILS = orig_admin_emails
