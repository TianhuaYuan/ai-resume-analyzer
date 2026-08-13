from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    password_confirm: str
    verification_code: str
    # CTA 来源渠道（?source=linkedin 之类），记录到产品分析事件
    source: str | None = Field(None, max_length=50, description="CTA 来源渠道")

    @field_validator("username")
    @classmethod
    def username_min_length(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("用户名至少2个字符")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("密码至少8位")
        if not any(c.isalpha() for c in v):
            raise ValueError("密码必须包含字母")
        if not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含数字")
        return v

    @field_validator("password_confirm")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("两次密码不一致")
        return v

    @field_validator("verification_code")
    @classmethod
    def verification_code_length(cls, v: str) -> str:
        if len(v) != 6 or not v.isdigit():
            raise ValueError("验证码必须是6位数字")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime
    # #9: 是否管理员（前端据此隐藏/显示管理后台入口）
    is_admin: bool = False

    model_config = {"from_attributes": True}  # 允许直接从ORM对象构建


class AdminResetPasswordRequest(BaseModel):
    email: EmailStr


class AdminResetPasswordResponse(BaseModel):
    email: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordVerifyRequest(BaseModel):
    email: EmailStr
    verification_code: str
    new_password: str

    @field_validator("verification_code")
    @classmethod
    def verification_code_length(cls, v: str) -> str:
        if len(v) != 6 or not v.isdigit():
            raise ValueError("验证码必须是6位数字")
        return v

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """复用注册密码强度规则。"""
        if len(v) < 8:
            raise ValueError("密码至少8位")
        if not any(c.isalpha() for c in v):
            raise ValueError("密码必须包含字母")
        if not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含数字")
        return v


class MessageResponse(BaseModel):
    """通用消息响应。"""
    detail: str


# ── 修改密码 ──────────────────────────────────────────


class ChangePasswordRequest(BaseModel):
    mode: str  # "password" | "code"
    old_password: str | None = None
    verification_code: str | None = None
    new_password: str

    @field_validator("mode")
    @classmethod
    def mode_valid(cls, v: str) -> str:
        if v not in ("password", "code"):
            raise ValueError("mode 必须是 password 或 code")
        return v

    @field_validator("verification_code")
    @classmethod
    def verification_code_length(cls, v: str | None) -> str | None:
        if v is not None and (len(v) != 6 or not v.isdigit()):
            raise ValueError("验证码必须是6位数字")
        return v

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("密码至少8位")
        if not any(c.isalpha() for c in v):
            raise ValueError("密码必须包含字母")
        if not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含数字")
        return v


# ── 修改邮箱 ──────────────────────────────────────────


class ChangeEmailRequest(BaseModel):
    new_email: EmailStr
    verification_code: str

    @field_validator("verification_code")
    @classmethod
    def verification_code_length(cls, v: str) -> str:
        if len(v) != 6 or not v.isdigit():
            raise ValueError("验证码必须是6位数字")
        return v


# ── 修改用户名 ──────────────────────────────────────────


class ChangeUsernameRequest(BaseModel):
    new_username: str

    @field_validator("new_username")
    @classmethod
    def username_min_length(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("用户名至少2个字符")
        if len(v.strip()) > 50:
            raise ValueError("用户名最多50个字符")
        return v.strip()
