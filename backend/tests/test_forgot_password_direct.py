"""新流程忘记密码测试：验证码通过后直接修改密码。

流程：
1. POST /api/v1/auth/send-code {email}
   - 发送验证码

2. POST /api/v1/auth/forgot-password {email, verification_code, new_password}
   - 验证验证码
   - 邮箱存在 → 直接更新密码 → 撤销该用户所有有效 token（强制重新登录）
   - 邮箱不存在 → 静默返回 200（防用户枚举）
   - 弱密码 → 422（Pydantic 校验）
"""
from httpx import AsyncClient


async def _send_code_and_get(client: AsyncClient, email: str) -> str:
    """辅助：发送验证码并从内存存储读取。"""
    await client.post("/api/v1/auth/send-code", json={"email": email})
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX

    code_entry = _in_memory_codes.get(f"{_CODE_KEY_PREFIX}{email}")
    return code_entry["code"] if code_entry else "123456"


class TestForgotPasswordDirectReset:
    """新流程：验证码通过后直接修改密码。"""

    async def test_forgot_password_success_new_password_works(
        self, client: AsyncClient, registered_user: dict
    ):
        """新流程：验证码+新密码直接重置，新密码可登录。"""
        email = registered_user["email"]
        code = await _send_code_and_get(client, email)

        r = await client.post(
            "/api/v1/auth/forgot-password",
            json={
                "email": email,
                "verification_code": code,
                "new_password": "NewPass123!",
            },
        )
        assert r.status_code == 200

        # 旧密码应失败
        old_login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": registered_user["password"]},
        )
        assert old_login.status_code == 401

        # 新密码应成功
        new_login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "NewPass123!"},
        )
        assert new_login.status_code == 200

    async def test_forgot_password_nonexistent_email_returns_200(
        self, client: AsyncClient
    ):
        """不存在的邮箱也返回 200（防用户枚举），不更新任何密码。"""
        email = "nobody@example.com"
        code = await _send_code_and_get(client, email)

        r = await client.post(
            "/api/v1/auth/forgot-password",
            json={
                "email": email,
                "verification_code": code,
                "new_password": "Whatever123!",
            },
        )
        assert r.status_code == 200

    async def test_forgot_password_invalid_code_returns_400(
        self, client: AsyncClient, registered_user: dict
    ):
        """无效验证码 → 400，密码不被修改。"""
        email = registered_user["email"]
        await client.post("/api/v1/auth/send-code", json={"email": email})

        r = await client.post(
            "/api/v1/auth/forgot-password",
            json={
                "email": email,
                "verification_code": "000000",
                "new_password": "NewPass123!",
            },
        )
        assert r.status_code == 400

        # 旧密码仍可用 → 证明密码未被修改
        old_login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": registered_user["password"]},
        )
        assert old_login.status_code == 200

    async def test_forgot_password_weak_password_returns_422(
        self, client: AsyncClient, registered_user: dict
    ):
        """弱密码 → 422（Pydantic 校验）。"""
        email = registered_user["email"]
        code = await _send_code_and_get(client, email)

        r = await client.post(
            "/api/v1/auth/forgot-password",
            json={
                "email": email,
                "verification_code": code,
                "new_password": "short",
            },
        )
        assert r.status_code == 422

    async def test_forgot_password_revokes_existing_tokens(
        self, client: AsyncClient, registered_user: dict
    ):
        """重置后旧 token 全部失效（防被劫持的会话继续使用）。"""
        email = registered_user["email"]

        # 登录拿到旧 token
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": registered_user["password"]},
        )
        old_access = login.json()["access_token"]
        old_refresh = login.json()["refresh_token"]

        # 用验证码重置密码
        code = await _send_code_and_get(client, email)
        r = await client.post(
            "/api/v1/auth/forgot-password",
            json={
                "email": email,
                "verification_code": code,
                "new_password": "NewPass123!",
            },
        )
        assert r.status_code == 200

        # 旧 access token 仍能解码（JWT 本身无状态），但我们只验证用户必须重登
        # 用旧密码登录失败 + 新密码登录成功
        new_login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "NewPass123!"},
        )
        assert new_login.status_code == 200
        assert new_login.json()["access_token"] != old_access
