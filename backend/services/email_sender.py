"""Task 1.2: 邮件发送抽象层。

设计目标
--------
1. **不绑死邮件服务商**：通过 `EmailSender` Protocol 抽象，开发/测试用 `LogEmailSender`，
   生产用 `SmtpEmailSender`（标准 `smtplib`，兼容阿里云/QQ/163/SendGrid 等任意 SMTP）。
2. **零门槛起步**：开发环境默认 `EMAIL_PROVIDER=log`，无 SMTP 账号也能跑通流程。
3. **可平滑切换**：仅需在 `.env` 改 `EMAIL_PROVIDER=smtp` + 配置 SMTP_*。

接口契约
--------
- `send_verification_email(to: str, code: str) -> None`：发送验证码邮件
- `build_verification_email(code, expire_minutes) -> tuple[str, str]`：返回 (html, text)
- `get_email_sender() -> EmailSender`：工厂函数，根据 `settings.EMAIL_PROVIDER` 返回实例

验证码有效期 5 分钟（与 services.verification_service._CODE_EXPIRE_MINUTES 对齐）。
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol

from core.config import settings

logger = logging.getLogger(__name__)

_VERIFICATION_EXPIRE_MINUTES = 5  # 与 services.verification_service._CODE_EXPIRE_MINUTES 对齐


# ── 邮件内容构建 ───────────────────────────────────────────────

def build_verification_email(code: str, expire_minutes: int) -> tuple[str, str]:
    """构建验证码邮件内容，返回 (html, text) 双版本。"""
    text = (
        "【AI Resume Analyzer】验证码\n"
        "\n"
        f"您的验证码是：{code}\n"
        "\n"
        f"验证码有效期：{expire_minutes} 分钟\n"
        "\n"
        "如果不是您本人操作，请忽略此邮件。\n"
    )

    html = f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<body style="font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif;
             max-width: 560px; margin: 0 auto; padding: 24px; color: #1e293b;">
  <h2 style="color: #4f46e5; margin-bottom: 16px;">AI Resume Analyzer — 验证码</h2>
  <p style="font-size: 14px; line-height: 1.6;">您好，</p>
  <p style="font-size: 14px; line-height: 1.6;">
    您正在进行邮箱验证，验证码如下：
  </p>
  <p style="margin: 24px 0; font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #1e293b;">
    {code}
  </p>
  <p style="font-size: 13px; color: #64748b; margin-top: 16px;">
    验证码有效期：{expire_minutes} 分钟，请尽快输入。
  </p>
  <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;">
  <p style="font-size: 12px; color: #94a3b8;">
    如果不是您本人操作，请忽略此邮件。<br>
    本邮件由系统自动发送，请勿回复。
  </p>
</body>
</html>
"""
    return html, text


# ── EmailSender 抽象 ──────────────────────────────────────────

class EmailSender(Protocol):
    """邮件发送接口（结构化子类型，无需显式继承）。"""

    def send_verification_email(self, to: str, code: str) -> None:
        """发送验证码邮件给指定收件人。"""
        ...


# ── LogEmailSender：开发环境用 ───────────────────────────────

class LogEmailSender:
    """开发环境 EmailSender：把邮件内容（含验证码）写入日志。"""

    def __init__(self, expire_minutes: int = _VERIFICATION_EXPIRE_MINUTES):
        self.expire_minutes = expire_minutes

    def send_verification_email(self, to: str, code: str) -> None:
        logger.info(
            "验证码邮件（开发日志）: to=%s code=%s (有效期 %d 分钟)",
            to,
            code,
            self.expire_minutes,
        )


# ── SmtpEmailSender：生产环境用 ──────────────────────────────

class SmtpEmailSender:
    """生产环境 EmailSender：通过 smtplib 发送真实邮件。

    支持两种连接模式：
    - SMTP_USE_TLS=False：使用 SMTP_SSL（端口 465，全程 SSL 加密）
    - SMTP_USE_TLS=True：使用 SMTP + starttls（端口 587，明文连接后升级为 TLS）

    兼容阿里云邮件推送 / SendGrid / QQ / 163 等任意 SMTP 服务器。
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool,
        from_addr: str,
        expire_minutes: int = _VERIFICATION_EXPIRE_MINUTES,
        timeout: int = 30,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_addr = from_addr
        self.expire_minutes = expire_minutes
        self.timeout = timeout

    def send_verification_email(self, to: str, code: str) -> None:
        html, text = build_verification_email(
            code=code,
            expire_minutes=self.expire_minutes,
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "【AI Resume Analyzer】验证码"
        msg["From"] = self.from_addr
        msg["To"] = to
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        if self.use_tls:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.from_addr, [to], msg.as_string())
        else:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout) as server:
                server.login(self.username, self.password)
                server.sendmail(self.from_addr, [to], msg.as_string())

        logger.info("验证码邮件已发送: to=%s", to)


# ── 工厂函数 ──────────────────────────────────────────────────

def get_email_sender() -> EmailSender:
    """根据 settings.EMAIL_PROVIDER 返回对应的 EmailSender 实例。

    Returns:
        - "log" → LogEmailSender（开发环境默认）
        - "smtp" → SmtpEmailSender（生产环境）

    Raises:
        ValueError: EMAIL_PROVIDER 为未知值
        RuntimeError: EMAIL_PROVIDER=smtp 但 SMTP_* 配置缺失
    """
    provider = settings.EMAIL_PROVIDER.lower()

    if provider == "log":
        return LogEmailSender()

    if provider == "smtp":
        # fail-fast：缺关键 SMTP 配置直接报错，避免带着错误配置启动后才发现邮件发不出去
        missing = []
        if not settings.SMTP_HOST.strip():
            missing.append("SMTP_HOST")
        if not settings.SMTP_USERNAME.strip():
            missing.append("SMTP_USERNAME")
        if not settings.SMTP_PASSWORD.strip():
            missing.append("SMTP_PASSWORD")
        if not settings.SMTP_FROM.strip():
            missing.append("SMTP_FROM")
        if missing:
            raise RuntimeError(
                "EMAIL_PROVIDER=smtp 但缺少 SMTP 配置: " + ", ".join(missing)
                + "。请在 .env 文件中补齐后再启动。"
            )

        return SmtpEmailSender(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            use_tls=settings.SMTP_USE_TLS,
            from_addr=settings.SMTP_FROM,
        )

    raise ValueError(
        f"EMAIL_PROVIDER={provider!r} 不支持，仅支持 'log' 或 'smtp'"
    )
