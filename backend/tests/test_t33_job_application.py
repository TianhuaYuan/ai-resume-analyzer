"""T33: 求职申请（Job Application）CRUD + 看板统计测试。

测试范围：
- POST /api/v1/jobs            创建求职申请
- GET  /api/v1/jobs            列表 + status 过滤 + 分页
- GET  /api/v1/jobs/{id}       查单条（404 / 归属隔离）
- PUT  /api/v1/jobs/{id}       部分更新
- DELETE /api/v1/jobs/{id}     删除
- GET  /api/v1/jobs/kanban     看板聚合统计（空 / 多条 / 状态分布）
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


async def _register_other_user(client: AsyncClient, username: str = "otheruser") -> dict:
    """注册第二个测试用户，返回其信息（用于归属隔离测试）。"""
    other_user_data = {
        "username": username,
        "email": f"{username}@example.com",
        "password": "Test1234!",
        "password_confirm": "Test1234!",
    }
    await client.post("/api/v1/auth/send-code", json={"email": other_user_data["email"]})
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX

    code_key = f"{_CODE_KEY_PREFIX}{other_user_data['email']}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"
    register_data = {**other_user_data, "verification_code": verification_code}
    resp = await client.post("/api/v1/auth/register", json=register_data)
    assert resp.status_code == 201
    return {**other_user_data, "id": resp.json()["id"]}


def _payload(**overrides) -> dict:
    """构造创建请求 body。"""
    base = {"company": "字节跳动", "position": "后端工程师"}
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════


class TestJobApplicationCRUD:
    """POST/GET/PUT/DELETE /api/v1/jobs"""

    @pytest.mark.asyncio
    async def test_create_application(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """正常创建，返回 201 + 完整字段。"""
        resp = await client.post(
            "/api/v1/jobs",
            json=_payload(city="北京", salary_range="25-40k", status="applied"),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] > 0
        assert data["user_id"] == registered_user["id"]
        assert data["company"] == "字节跳动"
        assert data["position"] == "后端工程师"
        assert data["city"] == "北京"
        assert data["salary_range"] == "25-40k"
        assert data["status"] == "applied"
        assert data["created_at"] is not None

    @pytest.mark.asyncio
    async def test_create_default_status(
        self, client: AsyncClient, auth_headers: dict
    ):
        """不传 status 时默认 wishlist。"""
        resp = await client.post(
            "/api/v1/jobs",
            json=_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "wishlist"

    @pytest.mark.asyncio
    async def test_create_invalid_status(
        self, client: AsyncClient, auth_headers: dict
    ):
        """status 不合法时返回 422。"""
        resp = await client.post(
            "/api/v1/jobs",
            json=_payload(status="invalid_status"),
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_missing_required_fields(
        self, client: AsyncClient, auth_headers: dict
    ):
        """缺 company / position 时返回 422。"""
        resp = await client.post(
            "/api/v1/jobs",
            json={"city": "北京"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_single_application(
        self, client: AsyncClient, auth_headers: dict
    ):
        """创建后 GET 单条。"""
        create = await client.post(
            "/api/v1/jobs", json=_payload(), headers=auth_headers
        )
        app_id = create.json()["id"]

        resp = await client.get(f"/api/v1/jobs/{app_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == app_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """不存在的 id 返回 404。"""
        resp = await client.get("/api/v1/jobs/99999", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_applications(
        self, client: AsyncClient, auth_headers: dict
    ):
        """列表返回创建的所有申请 + total。"""
        for i in range(3):
            await client.post(
                "/api/v1/jobs",
                json=_payload(company=f"公司{i}"),
                headers=auth_headers,
            )

        resp = await client.get("/api/v1/jobs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 3
        assert len(data["items"]) >= 3

    @pytest.mark.asyncio
    async def test_list_with_status_filter(
        self, client: AsyncClient, auth_headers: dict
    ):
        """status 过滤只返回匹配的。"""
        await client.post(
            "/api/v1/jobs",
            json=_payload(company="A", status="wishlist"),
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/jobs",
            json=_payload(company="B", status="interview"),
            headers=auth_headers,
        )

        resp = await client.get(
            "/api/v1/jobs?status=interview", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["status"] == "interview" for item in data["items"])
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_pagination(
        self, client: AsyncClient, auth_headers: dict
    ):
        """limit/offset 分页生效。"""
        for i in range(5):
            await client.post(
                "/api/v1/jobs",
                json=_payload(company=f"分页公司{i}"),
                headers=auth_headers,
            )

        resp = await client.get(
            "/api/v1/jobs?limit=2&offset=0", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] >= 5

    @pytest.mark.asyncio
    async def test_update_application(
        self, client: AsyncClient, auth_headers: dict
    ):
        """部分更新：改 status + city，其他字段不变。"""
        create = await client.post(
            "/api/v1/jobs",
            json=_payload(city="北京"),
            headers=auth_headers,
        )
        app_id = create.json()["id"]

        resp = await client.put(
            f"/api/v1/jobs/{app_id}",
            json={"status": "offer", "city": "上海"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "offer"
        assert data["city"] == "上海"
        # 未更新的字段保持不变
        assert data["company"] == "字节跳动"

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """更新不存在的 id 返回 404。"""
        resp = await client.put(
            "/api/v1/jobs/99999",
            json={"status": "applied"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_application(
        self, client: AsyncClient, auth_headers: dict
    ):
        """删除后 GET 返回 404。"""
        create = await client.post(
            "/api/v1/jobs", json=_payload(), headers=auth_headers
        )
        app_id = create.json()["id"]

        resp = await client.delete(f"/api/v1/jobs/{app_id}", headers=auth_headers)
        assert resp.status_code == 204

        resp2 = await client.get(f"/api/v1/jobs/{app_id}", headers=auth_headers)
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """删除不存在的 id 返回 404。"""
        resp = await client.delete("/api/v1/jobs/99999", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_ownership_isolation(
        self, client: AsyncClient, registered_user: dict, auth_headers: dict
    ):
        """用户 A 不能 GET/PUT/DELETE 用户 B 的申请（均返回 404）。"""
        # 用户 A 创建一条
        create = await client.post(
            "/api/v1/jobs", json=_payload(company="A的公司"), headers=auth_headers
        )
        app_id = create.json()["id"]

        # 注册用户 B 并登录
        other = await _register_other_user(client)
        resp_login = await client.post(
            "/api/v1/auth/login",
            json={"email": other["email"], "password": other["password"]},
        )
        assert resp_login.status_code == 200
        other_headers = {
            "Authorization": f"Bearer {resp_login.json()['access_token']}"
        }

        # B 尝试 GET A 的申请 → 404
        assert (
            await client.get(f"/api/v1/jobs/{app_id}", headers=other_headers)
        ).status_code == 404
        # B 尝试 PUT A 的申请 → 404
        assert (
            await client.put(
                f"/api/v1/jobs/{app_id}",
                json={"status": "rejected"},
                headers=other_headers,
            )
        ).status_code == 404
        # B 尝试 DELETE A 的申请 → 404
        assert (
            await client.delete(f"/api/v1/jobs/{app_id}", headers=other_headers)
        ).status_code == 404
        # B 的列表中看不到 A 的申请
        b_list = await client.get("/api/v1/jobs", headers=other_headers)
        assert b_list.status_code == 200
        assert b_list.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        """未认证访问任意接口 → 401。"""
        assert (await client.get("/api/v1/jobs")).status_code == 401
        assert (
            await client.post("/api/v1/jobs", json=_payload())
        ).status_code == 401


# ═══════════════════════════════════════════════════════════
# 看板统计
# ═══════════════════════════════════════════════════════════


class TestJobApplicationKanban:
    """GET /api/v1/jobs/kanban"""

    @pytest.mark.asyncio
    async def test_empty_stats(self, client: AsyncClient, auth_headers: dict):
        """无数据时返回全 0 / 空列表。"""
        resp = await client.get("/api/v1/jobs/kanban", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["by_status"] == {}
        assert data["by_company"] == []
        assert data["by_city"] == []
        assert data["trend"] == []

    @pytest.mark.asyncio
    async def test_stats_with_multiple_applications(
        self, client: AsyncClient, auth_headers: dict
    ):
        """多条申请的聚合统计。"""
        # 不同状态、不同公司、不同城市
        await client.post(
            "/api/v1/jobs",
            json=_payload(company="字节", city="北京", status="wishlist"),
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/jobs",
            json=_payload(company="字节", city="北京", status="applied"),
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/jobs",
            json=_payload(company="腾讯", city="深圳", status="interview"),
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/jobs",
            json=_payload(company="阿里", city="杭州", status="offer"),
            headers=auth_headers,
        )

        resp = await client.get("/api/v1/jobs/kanban", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 4
        # by_status
        assert data["by_status"]["wishlist"] == 1
        assert data["by_status"]["applied"] == 1
        assert data["by_status"]["interview"] == 1
        assert data["by_status"]["offer"] == 1
        # by_company top 5
        companies = {c["company"]: c["count"] for c in data["by_company"]}
        assert companies["字节"] == 2
        assert companies["腾讯"] == 1
        assert companies["阿里"] == 1
        # by_city top 5
        cities = {c["city"]: c["count"] for c in data["by_city"]}
        assert cities["北京"] == 2
        assert cities["深圳"] == 1
        assert cities["杭州"] == 1
        # trend 至少有今天的数据
        assert len(data["trend"]) >= 1
        assert data["trend"][0]["count"] >= 1

    @pytest.mark.asyncio
    async def test_stats_isolated_by_user(
        self, client: AsyncClient, auth_headers: dict
    ):
        """A 的统计数据不包含 B 的申请。"""
        # 用户 A 创建 2 条
        await client.post(
            "/api/v1/jobs", json=_payload(company="A公司"), headers=auth_headers
        )
        await client.post(
            "/api/v1/jobs", json=_payload(company="A公司2"), headers=auth_headers
        )

        # 用户 B 创建 1 条
        other = await _register_other_user(client)
        resp_login = await client.post(
            "/api/v1/auth/login",
            json={"email": other["email"], "password": other["password"]},
        )
        other_headers = {
            "Authorization": f"Bearer {resp_login.json()['access_token']}"
        }
        await client.post(
            "/api/v1/jobs", json=_payload(company="B公司"), headers=other_headers
        )

        # A 的统计 total=2，不含 B 的数据
        a_stats = await client.get("/api/v1/jobs/kanban", headers=auth_headers)
        assert a_stats.status_code == 200
        assert a_stats.json()["total"] == 2

        # B 的统计 total=1
        b_stats = await client.get("/api/v1/jobs/kanban", headers=other_headers)
        assert b_stats.status_code == 200
        assert b_stats.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_kanban_route_not_shadowed_by_id(
        self, client: AsyncClient, auth_headers: dict
    ):
        """确认 /jobs/kanban 没有被 /jobs/{id} 路由遮蔽（返回 200 而非 422）。"""
        resp = await client.get("/api/v1/jobs/kanban", headers=auth_headers)
        assert resp.status_code == 200
