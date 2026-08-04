"""爬虫管线工具纯函数测试（JobHunter 移植）。"""

from services.crawler.utils import clean_text, get_nested_value, parse_relative_date


def test_parse_relative_date_absolute():
    assert parse_relative_date("2024-01-15") == "2024-01-15"
    assert parse_relative_date("2024/1/5") == "2024-01-05"


def test_parse_relative_date_relative():
    assert parse_relative_date("今天") is not None
    assert parse_relative_date("昨天") is not None
    assert parse_relative_date("3天前") is not None
    assert parse_relative_date("1周前") is not None
    assert parse_relative_date("2个月前") is not None


def test_parse_relative_date_invalid():
    assert parse_relative_date("") is None
    assert parse_relative_date(None) is None
    assert parse_relative_date("无日期信息") is None


def test_clean_text_strips_tags_and_whitespace():
    assert clean_text("<b>Hello</b>   World") == "Hello World"
    assert clean_text("   ") == ""
    # 去标签 + 压缩空白；标签本身不产生分隔空格
    assert clean_text("<p>第一段</p><p>第二段</p>") == "第一段第二段"


def test_get_nested_value_path():
    obj = {"data": {"list": [{"name": "岗位A"}, {"name": "岗位B"}]}}
    assert get_nested_value(obj, "data.list.0.name") == "岗位A"
    assert get_nested_value(obj, "data.list.1.name") == "岗位B"
    assert get_nested_value(obj, "data.missing") is None
    assert get_nested_value({"a": 1}, "b.c.d") is None
