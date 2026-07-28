"""验证码服务测试。"""
import pytest
from services.verification_service import (
    generate_code,
    store_code,
    verify_code,
    clear_code,
)


class TestVerificationCode:
    """验证码生成与验证测试。"""

    def test_generate_code_returns_6_digit(self):
        """生成的验证码应为6位数字。"""
        code = generate_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_generate_code_is_random(self):
        """生成的验证码应具有随机性。"""
        codes = {generate_code() for _ in range(10)}
        assert len(codes) > 1  # 至少有2个不同的码

    @pytest.mark.asyncio
    async def test_store_and_verify_code_success(self):
        """存储验证码后验证应成功。"""
        email = "test@example.com"
        code = generate_code()
        await store_code(email, code)
        result = await verify_code(email, code)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_wrong_code_fails(self):
        """错误的验证码应验证失败。"""
        email = "test@example.com"
        code = generate_code()
        await store_code(email, code)
        result = await verify_code(email, "123456")
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_nonexistent_email_fails(self):
        """验证不存在的邮箱应失败。"""
        result = await verify_code("nonexistent@example.com", "123456")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear_code_removes_code(self):
        """清除验证码后再次验证应失败。"""
        email = "test@example.com"
        code = generate_code()
        await store_code(email, code)
        await clear_code(email)
        result = await verify_code(email, code)
        assert result is False