"""阶段性收尾回归测试：覆盖本次修复的 CRITICAL/HIGH 缺陷。

- 头像删除路径穿越防护（delete_avatar 目录约束）
- 脱敏占位符落库前还原（_restore_sensitive_placeholders）
"""

import pytest

from services.avatar_service import delete_avatar
from services.react_agent.tools.__init__ import _restore_sensitive_placeholders


def test_delete_avatar_rejects_path_traversal(tmp_path, monkeypatch):
    """delete_avatar 拒绝目录外路径（路径穿越防护）。"""
    from core.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    avatars = tmp_path / "avatars"
    avatars.mkdir()
    trap = tmp_path.parent / "trap.txt"
    trap.write_text("secret")

    # 路径穿越 → 拒绝，陷阱文件保留
    assert delete_avatar(f"/uploads/avatars/../../{trap.name}") is False
    assert trap.exists()

    # 目录内合法头像 → 正常删除
    real = avatars / "abc.jpg"
    real.write_text("x")
    assert delete_avatar("/uploads/avatars/abc.jpg") is True
    assert not real.exists()


def test_delete_avatar_ignores_empty():
    """空/None 头像直接跳过。"""
    assert delete_avatar("") is False
    assert delete_avatar(None) is False  # type: ignore[arg-type]


def test_restore_sensitive_placeholders():
    """脱敏占位符在落库前还原为真实值（before 快照）。"""
    before = [
        {
            "module_type": "basic_info",
            "content": {"name": "张三", "phone": "13800138000", "email": "a@b.com"},
        }
    ]
    modules = [
        {
            "module_type": "basic_info",
            "content": {"name": "[姓名]", "summary": "手机 [手机号] 邮箱 [邮箱]"},
        },
        {
            "module_type": "work_experience",
            "content": {"items": [{"company": "[姓名]公司"}]},
        },
    ]
    out = _restore_sensitive_placeholders(modules, before)
    assert out[0]["content"]["name"] == "张三"
    assert out[0]["content"]["summary"] == "手机 13800138000 邮箱 a@b.com"
    assert out[1]["content"]["items"][0]["company"] == "张三公司"


def test_restore_sensitive_no_before_keeps_as_is():
    """无 before 快照时保持原样（不还原）。"""
    modules = [{"module_type": "basic_info", "content": {"name": "[姓名]"}}]
    out = _restore_sensitive_placeholders(modules, [])
    assert out[0]["content"]["name"] == "[姓名]"
