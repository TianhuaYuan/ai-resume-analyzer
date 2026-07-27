"""Task 1.2: EmailSender 抽象层测试。

TDD RED 阶段：先写测试，规定接口形态。
- LogEmailSender：开发环境用，把 reset_token 和链接写入日志
- SmtpEmailSender：生产环境用，通过 smtplib 发送 HTML + 纯文本邮件
- build_reset_email：构建邮件内容（HTML + 纯文本双版本），含重置链接
- get_email_sender：根据 settings.EMAIL_PROVIDER 返回对应实现
"""
import logging
from email import message_from_string
from unittest.mock import MagicMock, patch

import pytest

from core.config import settings
from services.email_sender import (
    LogEmailSender,
    SmtpEmailSender,
    build_reset_email,
    get_email_sender,
)


class TestBuildResetEmail:
    """邮件内容构建器测试。"""

    def test_build_returns_html_and_text_pair(self):
        """build_reset_email 应返回 (html, text) 二元组。"""
        html, text = build_reset_email(
            token="abc123",
            base_url="http://localhost:5173",
            expire_minutes=30,
        )
        assert isinstance(html, str)
        assert isinstance(text, str)
        assert len(html) > 0
        assert len(text) > 0

    def test_html_contains_reset_link(self):
        """HTML 邮件必须含完整重置链接（base_url + token）。"""
        html, _ = build_reset_email(
            token="abc123",
            base_url="http://localhost:5173",
            expire_minutes=30,
        )
        expected_link = "http://localhost:5173/reset-password?token=abc123"
        assert expected_link in html, f"HTML 应含重置链接 {expected_link}"

    def test_text_contains_reset_link(self):
        """纯文本邮件也必须含完整重置链接。"""
        _, text = build_reset_email(
            token="abc123",
            base_url="http://localhost:5173",
            expire_minutes=30,
        )
        expected_link = "http://localhost:5173/reset-password?token=abc123"
        assert expected_link in text

    def test_html_contains_expire_minutes(self):
        """HTML 邮件应显示 token 有效期（分钟），帮助用户知道链接何时过期。"""
        html, _ = build_reset_email(
            token="abc123",
            base_url="http://localhost:5173",
            expire_minutes=30,
        )
        assert "30" in html, "邮件应显示有效期 30 分钟"

    def test_text_contains_expire_minutes(self):
        """纯文本邮件也应显示有效期。"""
        _, text = build_reset_email(
            token="abc123",
            base_url="http://localhost:5173",
            expire_minutes=30,
        )
        assert "30" in text


class TestLogEmailSender:
    """LogEmailSender 测试：开发环境用，写日志而非真实发邮件。"""

    def test_send_reset_email_writes_token_to_log(self, caplog):
        """LogEmailSender.send_reset_email 应将 reset_token 写入日志，供测试提取。"""
        caplog.set_level(logging.INFO, logger="services.email_sender")
        sender = LogEmailSender(base_url="http://localhost:5173", expire_minutes=30)

        sender.send_reset_email(to="user@example.com", token="abc123")

        # 日志中应能提取到 token 和重置链接
        log_text = "\n".join(r.getMessage() for r in caplog.records)
        assert "abc123" in log_text, "日志中应记录 reset_token"
        assert "http://localhost:5173/reset-password?token=abc123" in log_text, (
            "日志中应记录完整重置链接"
        )

    def test_send_reset_email_logs_recipient(self, caplog):
        """日志应记录收件人邮箱（便于开发联调定位）。"""
        caplog.set_level(logging.INFO, logger="services.email_sender")
        sender = LogEmailSender(base_url="http://localhost:5173", expire_minutes=30)

        sender.send_reset_email(to="user@example.com", token="abc123")

        log_text = "\n".join(r.getMessage() for r in caplog.records)
        assert "user@example.com" in log_text


class TestSmtpEmailSender:
    """SmtpEmailSender 测试：用 mock smtplib，不真实发邮件。"""

    def _decode_email_body(self, raw_email: str) -> tuple[str, str]:
        """从 sendmail 的原始邮件字符串中提取 (text, html) 解码后内容。

        MIMEText 默认 base64 编码中文，需要 get_payload(decode=True) 才能拿到原文。
        """
        msg = message_from_string(raw_email)
        text_part = ""
        html_part = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    text_part = part.get_payload(decode=True).decode("utf-8", errors="replace")
                elif ctype == "text/html":
                    html_part = part.get_payload(decode=True).decode("utf-8", errors="replace")
        else:
            # 非 multipart，单一 body
            content = msg.get_payload(decode=True).decode("utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                html_part = content
            else:
                text_part = content
        return text_part, html_part

    def test_send_reset_email_uses_smtp_ssl_when_tls_disabled(self):
        """SMTP_USE_TLS=False 时应使用 SMTP_SSL（端口 465 默认）。"""
        sender = SmtpEmailSender(
            host="smtp.example.com",
            port=465,
            username="noreply@example.com",
            password="pass",
            use_tls=False,
            from_addr="noreply@example.com",
            base_url="http://localhost:5173",
            expire_minutes=30,
        )

        with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
            mock_server = MagicMock()
            mock_smtp_ssl.return_value.__enter__.return_value = mock_server

            sender.send_reset_email(to="user@example.com", token="abc123")

            mock_smtp_ssl.assert_called_once_with("smtp.example.com", 465, timeout=30)
            mock_server.login.assert_called_once_with("noreply@example.com", "pass")
            mock_server.sendmail.assert_called_once()
            args = mock_server.sendmail.call_args[0]
            assert args[0] == "noreply@example.com"
            assert "user@example.com" in args[1]
            # 解码 MIME 邮件后验证正文含重置链接（base64 编码后无法直接断言）
            text, html = self._decode_email_body(args[2])
            expected_link = "http://localhost:5173/reset-password?token=abc123"
            assert expected_link in text, "纯文本部分应含重置链接"
            assert expected_link in html, "HTML 部分应含重置链接"

    def test_send_reset_email_uses_smtp_when_tls_enabled(self):
        """SMTP_USE_TLS=True 时应使用 SMTP + starttls（端口 587 默认）。"""
        sender = SmtpEmailSender(
            host="smtp.example.com",
            port=587,
            username="noreply@example.com",
            password="pass",
            use_tls=True,
            from_addr="noreply@example.com",
            base_url="http://localhost:5173",
            expire_minutes=30,
        )

        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server

            sender.send_reset_email(to="user@example.com", token="abc123")

            mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=30)
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("noreply@example.com", "pass")
            mock_server.sendmail.assert_called_once()

    def test_email_content_has_multipart_alternative(self):
        """邮件应为 multipart/alternative，同时携带 text/html 和 text/plain。"""
        sender = SmtpEmailSender(
            host="smtp.example.com",
            port=465,
            username="noreply@example.com",
            password="pass",
            use_tls=False,
            from_addr="noreply@example.com",
            base_url="http://localhost:5173",
            expire_minutes=30,
        )

        with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
            mock_server = MagicMock()
            mock_smtp_ssl.return_value.__enter__.return_value = mock_server

            sender.send_reset_email(to="user@example.com", token="abc123")

            args = mock_server.sendmail.call_args[0]
            msg = message_from_string(args[2])
            assert msg.is_multipart(), "邮件应为 multipart 结构"
            ctypes = [part.get_content_type() for part in msg.walk() if not part.is_multipart()]
            assert "text/plain" in ctypes, "邮件应含纯文本版本"
            assert "text/html" in ctypes, "邮件应含 HTML 版本"


class TestGetEmailSenderFactory:
    """工厂函数测试：根据 EMAIL_PROVIDER 返回对应实现。"""

    def test_returns_log_sender_when_provider_is_log(self, monkeypatch):
        """EMAIL_PROVIDER=log 返回 LogEmailSender。"""
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "log")
        sender = get_email_sender()
        assert isinstance(sender, LogEmailSender)

    def test_returns_smtp_sender_when_provider_is_smtp(self, monkeypatch):
        """EMAIL_PROVIDER=smtp 返回 SmtpEmailSender。"""
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
        monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(settings, "SMTP_PORT", 465)
        monkeypatch.setattr(settings, "SMTP_USERNAME", "noreply@example.com")
        monkeypatch.setattr(settings, "SMTP_PASSWORD", "pass")
        monkeypatch.setattr(settings, "SMTP_USE_TLS", False)
        monkeypatch.setattr(settings, "SMTP_FROM", "noreply@example.com")
        sender = get_email_sender()
        assert isinstance(sender, SmtpEmailSender)

    def test_unknown_provider_raises_value_error(self, monkeypatch):
        """未知 EMAIL_PROVIDER 应抛 ValueError，fail-fast 防止配置错误静默通过。"""
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "unknown")
        with pytest.raises(ValueError, match="EMAIL_PROVIDER"):
            get_email_sender()

    def test_smtp_provider_missing_host_raises(self, monkeypatch):
        """EMAIL_PROVIDER=smtp 但 SMTP_HOST 为空应抛 RuntimeError（启动期 fail-fast）。"""
        monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
        monkeypatch.setattr(settings, "SMTP_HOST", "")
        with pytest.raises((RuntimeError, ValueError)):
            get_email_sender()
