"""RecommendJobsTool 测试：归属校验 / 非 ready 409 / sources 填充 / 排序。"""

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from models.resume import Resume
from models.user import User
from services import market_match_service
from services.react_agent.tools import RecommendJobsTool


async def _seed_user(db_session, user_id: int = 1):
    db_session.add(User(
        id=user_id, username="tester", email="tester@example.com",
        password_hash="x", password_changed_at=None,
    ))
    await db_session.commit()


async def _seed_ready_resume(db_session, resume_id: int = 10):
    await _seed_user(db_session)
    db_session.add(Resume(
        id=resume_id, user_id=1, filename="test.pdf", file_path="/tmp/test.pdf",
        status="ready", parsed_text="熟悉 Python 和机器学习",
    ))
    await db_session.commit()


def _fake_items():
    return [
        {
            "id": 2, "title": "后端开发", "company": "B公司", "position": "后端开发",
            "city": "上海", "salary": "25-45K", "job_type": "campus",
            "score": 90, "matched": ["Python"], "gaps": [], "reason": "高度匹配",
        },
        {
            "id": 1, "title": "算法工程师", "company": "A公司", "position": "算法工程师",
            "city": "北京", "salary": "20-40K", "job_type": "campus",
            "score": 80, "matched": [], "gaps": ["分布式"], "reason": "较匹配",
        },
    ]


def _build_tool(db, user_id):
    return RecommendJobsTool(db=db, user_id=user_id)


@pytest.mark.asyncio
async def test_recommend_fills_sources(db_session):
    """推荐成功后 self.sources 被填充，返回 Markdown 含岗位与分数。"""
    await _seed_ready_resume(db_session)
    tool = _build_tool(db_session, user_id=1)
    with patch.object(market_match_service, "recommend_jobs",
                      new=AsyncMock(return_value=_fake_items())):
        result = await tool.execute(resume_id=10, top_k=2)

    assert "后端开发" in result
    assert "90" in result  # 匹配分
    assert len(tool.sources) == 2
    assert tool.sources[0]["score"] == 90  # 排序后第一个是最高分
    assert tool.sources[0]["title"] == "后端开发"


@pytest.mark.asyncio
async def test_recommend_rejects_foreign_resume(db_session):
    """简历非本人 → 归属校验拒绝，返回提示而非执行推荐。"""
    tool = _build_tool(db_session, user_id=1)
    with patch.object(market_match_service, "recommend_jobs",
                      new=AsyncMock(return_value=_fake_items())) as mock_rec:
        result = await tool.execute(resume_id=999)

    assert "不存在或无权访问" in result
    mock_rec.assert_not_awaited()


@pytest.mark.asyncio
async def test_recommend_409_on_not_ready(db_session):
    """简历未就绪（draft/processing）→ 返回 ⚠️ 提示。"""
    await _seed_user(db_session)
    db_session.add(Resume(
        id=1, user_id=1, filename="test.pdf", file_path="/tmp/test.pdf", status="draft",
        parsed_text="未完成的简历",
    ))
    await db_session.commit()

    tool = _build_tool(db_session, user_id=1)
    with patch.object(
        market_match_service, "recommend_jobs",
        new=AsyncMock(side_effect=HTTPException(status_code=409, detail="简历未就绪（当前状态: draft）")),
    ):
        result = await tool.execute(resume_id=1)

    assert "⚠️" in result
    assert "未就绪" in result


@pytest.mark.asyncio
async def test_recommend_empty_returns_guidance(db_session):
    """无匹配岗位时返回引导文案。"""
    await _seed_ready_resume(db_session)
    tool = _build_tool(db_session, user_id=1)
    with patch.object(market_match_service, "recommend_jobs",
                      new=AsyncMock(return_value=[])):
        result = await tool.execute(resume_id=10)

    assert "没有找到" in result
    assert tool.sources == []
