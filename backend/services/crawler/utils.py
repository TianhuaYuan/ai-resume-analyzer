"""爬虫管线纯函数工具（无 I/O，直接从 third_party/JobHunter 翻译，MIT）。

与 JobHunter 对照：
    parse_relative_date ← base_crawler.BaseCrawler.parse_relative_date
    clean_text           ← base_crawler.BaseCrawler.clean_text
    get_nested_value     ← api_crawler.ApiCrawler._get_nested_value

这三个函数都是纯函数（只依赖标准库，不碰网络/文件/浏览器），
可安全地用于同步归一化、单元测试、以及任何需要字符串/日期清洗的场景。
"""

import re
from datetime import datetime, timedelta
from typing import Any

# ── 正则（预编译，避免重复编译开销） ─────────────────────────────

# 绝对日期：2024-01-15 / 2024/1/15
_ABSOLUTE_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
# 月-日（当年）：01-15 / 1/15
_MD_DATE_RE = re.compile(r"(\d{1,2})[-/](\d{1,2})")
# 相对日期：3天前 / 1周前 / 2个月前（"发布于 3 天前"也能匹配，search 定位数字）
_REL_DAYS_RE = re.compile(r"(\d+)\s*天前")
_REL_WEEKS_RE = re.compile(r"(\d+)\s*周前")
_REL_MONTHS_RE = re.compile(r"(\d+)\s*个月前")
# 清理
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def parse_relative_date(date_text: str) -> str | None:
    """把中文相对日期 / 绝对日期归一化为 ``YYYY-MM-DD`` 字符串。

    支持的输入（对照 JobHunter base_crawler.parse_relative_date）：
        - "今天" / "昨天"
        - "3天前" / "1周前" / "2个月前" / "1个月前"（数字与单位间允许空格，允许"发布于"前缀）
        - "2024-01-15" / "2024/1/15"（绝对日期）
        - "01-15" / "1/15"（当年月日）
    无法解析（或输入为空 / 纯空白）返回 ``None``。

    边界说明：
        - 相对日期以调用时刻的本地日期为基准（与 JobHunter 一致）。
        - "X个月前"按每月 30 天近似（JobHunter 原逻辑，非日历月）。
        - 绝对日期中的月/日会补零为两位（``2024/1/15`` → ``2024-01-15``）。
        - 带时间的完整时间戳（如 ``2026-07-31 13:39:08``）也会被绝对日期分支
          命中并归一到 ``YYYY-MM-DD``（丢弃时间）；若需保留时分秒，请直接
          透传给 ``market_sync_service._parse_dt`` 而非本函数。

    Args:
        date_text: 原始日期文本，可为空字符串 / ``None``。

    Returns:
        ``YYYY-MM-DD`` 字符串；解析失败返回 ``None``。
    """
    if not date_text:
        return None
    text = str(date_text).strip()
    if not text:
        return None

    today = datetime.now()

    if "今天" in text:
        return today.strftime("%Y-%m-%d")
    if "昨天" in text:
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")

    m = _REL_DAYS_RE.search(text)
    if m:
        return (today - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    m = _REL_WEEKS_RE.search(text)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).strftime("%Y-%m-%d")
    m = _REL_MONTHS_RE.search(text)
    if m:
        # JobHunter 原逻辑：月份按 30 天近似
        return (today - timedelta(days=int(m.group(1)) * 30)).strftime("%Y-%m-%d")

    m = _ABSOLUTE_DATE_RE.search(text)
    if m:
        year, month, day = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    m = _MD_DATE_RE.search(text)
    if m:
        month, day = m.groups()
        return f"{today.year}-{int(month):02d}-{int(day):02d}"

    return None


def clean_text(text: str) -> str:
    """清理文本：去 HTML 标签 + 压缩连续空白（对照 JobHunter base_crawler.clean_text）。

    处理步骤：
        1. 去除所有 ``<...>`` HTML/XML 标签
        2. 连续空白（含换行/制表符）压缩为单个空格
        3. 去除首尾空白

    边界说明：
        - 输入为 ``None`` / 空串 / 非字符串 → 返回 ``""``。
        - 嵌套标签（``<div><b>x</b></div>``）会被一并去除，内容保留。
        - 纯标签串（``<br/><p></p>``）会返回 ``""``。

    Args:
        text: 原始文本（可为 ``None``）。

    Returns:
        清理后的文本；空输入返回 ``""``。
    """
    if not text:
        return ""
    s = _HTML_TAG_RE.sub("", str(text))
    s = _WHITESPACE_RE.sub(" ", s)
    return s.strip()


def get_nested_value(obj: Any, path: str) -> Any:
    """按点路径取嵌套值（对照 JobHunter api_crawler.ApiCrawler._get_nested_value）。

    例如：``get_nested_value(resp, "data.job_post_list")`` 等价于
    ``resp["data"]["job_post_list"]``。

    边界说明：
        - 路径为空 / ``obj`` 非 dict-list 结构 → 返回 ``None``。
        - 路径中间某段缺失 → 返回 ``None``（不抛 KeyError）。
        - 路径段为纯数字且当前值是 list → 按索引取值（越界返回 ``None``），
          这是相对 JobHunter 的一个小增强（原版仅支持 dict 遍历）。
        - ``obj`` 为 ``None`` 时也安全返回 ``None``。

    Args:
        obj: 要取值的对象（通常是解析后的 JSON dict / list）。
        path: 点分隔路径，如 ``"data.job_post_list"`` / ``"list.0.name"``。

    Returns:
        命中值；任意一步取不到返回 ``None``。
    """
    if not path:
        return None
    value = obj
    for key in str(path).split("."):
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit():
            try:
                value = value[int(key)]
            except IndexError:
                return None
        else:
            return None
    return value
