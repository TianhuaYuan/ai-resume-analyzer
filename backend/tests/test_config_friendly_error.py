"""config.py Settings 启动崩溃友好提示测试。

原行为：pydantic 校验失败抛 ValidationError，错误信息缺：
- 当前 APP_ENV 对应哪个 .env 文件
- 哪个字段缺失/不合法
- 解决方向

修复后：`_format_settings_error(e, app_env)` 函数生成友好中文提示，
config.py 模块加载时捕获 ValidationError 并打印该提示后重新抛出。

测试策略：直接调用 `_format_settings_error`，构造模拟的 ValidationError，
验证提示文本包含关键信息。避免重新 import core.config 污染 sys.modules。
"""
from unittest.mock import MagicMock

from pydantic import ValidationError

from core.config import _format_settings_error


def _make_validation_error(field_locs: list[str]) -> ValidationError:
    """构造模拟的 ValidationError，避免真的实例化失败的 Settings。"""
    fake_err = MagicMock(spec=ValidationError)
    fake_err.errors.return_value = [
        {"loc": (loc,), "msg": "field required", "type": "missing"}
        for loc in field_locs
    ]
    return fake_err


def test_format_error_contains_app_env_and_env_file():
    """友好提示应包含 APP_ENV 值和对应的 .env 文件名。"""
    err = _make_validation_error(["DATABASE_URL"])
    hint = _format_settings_error(err, app_env="prod")

    assert "APP_ENV='prod'" in hint, "应提示当前 APP_ENV 值"
    assert ".env.prod" in hint, "应提示期望读取的 .env 文件名"


def test_format_error_lists_failed_fields():
    """友好提示应列出所有失败字段名。"""
    err = _make_validation_error(["DATABASE_URL", "CHAT_API_KEY", "JWT_SECRET_KEY"])
    hint = _format_settings_error(err, app_env="dev")

    assert "DATABASE_URL" in hint
    assert "CHAT_API_KEY" in hint
    assert "JWT_SECRET_KEY" in hint
    assert "失败字段" in hint


def test_format_error_contains_solution_hints():
    """友好提示应给出具体解决方向。"""
    err = _make_validation_error(["DATABASE_URL"])
    hint = _format_settings_error(err, app_env="test")

    assert "解决方向" in hint
    # 三条具体解决方向
    assert "检查 backend/.env.test" in hint, "应提示检查 .env 文件"
    assert "检查 APP_ENV 环境变量" in hint, "应提示检查 APP_ENV"
    assert "检查字段值是否合法" in hint, "应提示检查字段值"


def test_format_error_handles_empty_loc():
    """边界：ValidationError.errors() 返回空列表时不崩溃。"""
    fake_err = MagicMock(spec=ValidationError)
    fake_err.errors.return_value = []
    hint = _format_settings_error(fake_err, app_env="dev")

    # 应回退到"详见上方错误"
    assert "详见上方错误" in hint
    assert "配置加载失败" in hint


def test_format_error_has_visual_separator():
    """友好提示应有视觉分隔，便于在长日志中识别。"""
    err = _make_validation_error(["DATABASE_URL"])
    hint = _format_settings_error(err, app_env="dev")

    # 应有 === 分隔线突出显示
    assert "=" * 30 in hint, "应有 === 视觉分隔线"
    assert "❌" in hint, "应有错误标识符号"
