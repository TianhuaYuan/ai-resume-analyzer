"""职责重定位：业务模块一键归档为知识资产（/api/v1/{interviews,job-applications}/{id}/archive）。

覆盖：投递 JD / 面试复盘归档创建、幂等 upsert、越权 404、软删/无 JD 400、
归档文本含评分卡摘要、re-archive 覆盖更新。
"""

import pytest


async def _register_other(client, username="other", email="other@example.com"):
    """注册第二个用户并返回其 auth headers。"""
    data = {
        "username": username,
        "email": email,
        "password": "Test1234!",
        "password_confirm": "Test1234!",
    }
    await client.post("/api/v1/auth/send-code", json={"email": data["email"]})
    from services.verification_service import _CODE_KEY_PREFIX, _in_memory_codes

    code = _in_memory_codes.get(f"{_CODE_KEY_PREFIX}{data['email']}")["code"]
    await client.post("/api/v1/auth/register", json={**data, "verification_code": code})
    login = await client.post(
        "/api/v1/auth/login", json={"email": data["email"], "password": data["password"]}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create_application(client, headers, **overrides):
    body = {
        "company": "字节",
        "position": "后端开发",
        "jd_text": "精通 Python，负责高并发服务",
    }
    body.update(overrides)
    resp = await client.post("/api/v1/job-applications", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["application"]


async def _create_interview(client, headers, **overrides):
    body = {
        "company": "字节",
        "position": "后端开发",
        "questions": ["讲一下你的项目"],
        "answers": ["独立设计并实现了……"],
    }
    body.update(overrides)
    resp = await client.post("/api/v1/interviews", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── 投递归档 ──


@pytest.mark.asyncio
async def test_archive_application_creates_jd_asset(client, auth_headers):
    app = await _create_application(client, auth_headers)
    resp = await client.post(
        f"/api/v1/job-applications/{app['id']}/archive", headers=auth_headers
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["asset_type"] == "jd"
    assert data["source_type"] == "job_application"
    assert data["source_id"] == app["id"]
    assert data["is_draft"] is False
    assert app["company"] in data["title"]
    assert app["jd_text"] in data["content"]


@pytest.mark.asyncio
async def test_archive_application_idempotent(client, auth_headers):
    """重复归档不重复建资产：同来源覆盖更新，列表仅 1 条。"""
    app = await _create_application(client, auth_headers)
    r1 = (
        await client.post(f"/api/v1/job-applications/{app['id']}/archive", headers=auth_headers)
    ).json()
    r2 = (
        await client.post(f"/api/v1/job-applications/{app['id']}/archive", headers=auth_headers)
    ).json()
    assert r1["id"] == r2["id"]

    resp = await client.get("/api/v1/assets?asset_type=jd", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["id"] == r1["id"]


@pytest.mark.asyncio
async def test_archive_application_isolation(client, auth_headers):
    """他人归档我的投递 → 404（防枚举）。"""
    app = await _create_application(client, auth_headers)
    other_headers = await _register_other(client, username="other1", email="other1@example.com")
    resp = await client.post(
        f"/api/v1/job-applications/{app['id']}/archive", headers=other_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_archive_application_not_found(client, auth_headers):
    resp = await client.post("/api/v1/job-applications/99999/archive", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_archive_application_soft_deleted_rejected(client, auth_headers):
    app = await _create_application(client, auth_headers)
    await client.delete(f"/api/v1/job-applications/{app['id']}", headers=auth_headers)
    resp = await client.post(
        f"/api/v1/job-applications/{app['id']}/archive", headers=auth_headers
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_archive_application_no_jd_rejected(client, auth_headers):
    app = await _create_application(client, auth_headers, jd_text=None)
    resp = await client.post(
        f"/api/v1/job-applications/{app['id']}/archive", headers=auth_headers
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_archive_application_upsert_updates_content(client, auth_headers):
    """改投递 JD 后 re-archive → 资产内容覆盖、version 递增。"""
    app = await _create_application(client, auth_headers, jd_text="v1 版本 JD")
    r1 = (
        await client.post(f"/api/v1/job-applications/{app['id']}/archive", headers=auth_headers)
    ).json()

    await client.put(
        f"/api/v1/job-applications/{app['id']}",
        json={"jd_text": "v2 版本 JD 更新"},
        headers=auth_headers,
    )
    r2 = (
        await client.post(f"/api/v1/job-applications/{app['id']}/archive", headers=auth_headers)
    ).json()
    assert r1["id"] == r2["id"]
    assert "v2 版本 JD 更新" in r2["content"]
    assert r2["version"] > r1["version"]


# ── 面试归档 ──


@pytest.mark.asyncio
async def test_archive_interview_creates_asset(client, auth_headers):
    itv = await _create_interview(client, auth_headers)
    resp = await client.post(f"/api/v1/interviews/{itv['id']}/archive", headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["asset_type"] == "interview"
    assert data["source_type"] == "interview_session"
    assert data["source_id"] == itv["id"]
    assert data["is_draft"] is False
    assert itv["company"] in data["title"]
    assert "讲一下你的项目" in data["content"]


@pytest.mark.asyncio
async def test_archive_interview_idempotent(client, auth_headers):
    itv = await _create_interview(client, auth_headers)
    r1 = (
        await client.post(f"/api/v1/interviews/{itv['id']}/archive", headers=auth_headers)
    ).json()
    r2 = (
        await client.post(f"/api/v1/interviews/{itv['id']}/archive", headers=auth_headers)
    ).json()
    assert r1["id"] == r2["id"]

    resp = await client.get("/api/v1/assets?asset_type=interview", headers=auth_headers)
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_archive_interview_isolation(client, auth_headers):
    itv = await _create_interview(client, auth_headers)
    other_headers = await _register_other(client, username="other2", email="other2@example.com")
    resp = await client.post(f"/api/v1/interviews/{itv['id']}/archive", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_archive_interview_not_found(client, auth_headers):
    resp = await client.post("/api/v1/interviews/99999/archive", headers=auth_headers)
    assert resp.status_code == 404


# ── 归档文本纯函数（含评分卡摘要）──


@pytest.mark.asyncio
async def test_build_jd_asset_content_includes_scorecard(db_session, test_user):
    from models.job_application import JobApplication
    from services.asset_service import build_jd_asset_content

    app = JobApplication(
        user_id=test_user.id,
        company="腾讯",
        position="前端工程师",
        jd_text="熟悉 React 与性能优化",
        jd_scorecard={
            "grade": "B",
            "comp_min": 15,
            "comp_max": 25,
            "pain_line": "项目节奏快",
            "gaps": ["性能优化", "跨端"],
        },
    )
    db_session.add(app)
    await db_session.commit()

    text = build_jd_asset_content(app)
    assert "腾讯 前端工程师 JD" in text
    assert "Grade: B" in text
    assert "15-25" in text
    assert "痛点" in text and "项目节奏快" in text
    assert "差距项" in text and "性能优化" in text


@pytest.mark.asyncio
async def test_build_interview_asset_content_includes_scorecard(db_session, test_user):
    from models.interview_session import InterviewSession
    from services.asset_service import build_interview_asset_content

    s = InterviewSession(
        user_id=test_user.id,
        company="字节",
        position="后端开发",
        jd_text="JD 原文",
        questions=["讲一下项目", "算法题"],
        answers=["……", "……"],
        scorecard={"overall_score": 60, "weak_competencies": ["算法"]},
        notes="一面复盘",
    )
    db_session.add(s)
    await db_session.commit()

    text = build_interview_asset_content(s)
    assert "字节 后端开发 面试复盘" in text
    assert "Q1" in text and "Q2" in text
    assert "JD 原文" in text
    assert "算法" in text  # 评分卡摘要
    assert "一面复盘" in text
