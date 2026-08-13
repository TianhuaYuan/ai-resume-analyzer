"""A2: 结构化抽取增强测试（SmartResume 索引指针机制）。

覆盖：
- _index_lines：行号索引 + 原文行列表
- _resolve_line_refs：合法引用切片还原 / 非法引用保留 / 嵌套结构递归 / 标量不受影响
- 端到端（mock LLM）：带 lines 引用的输出校验通过，长字段为原文切片
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.resume_parser import (
    _coerce_rich_text_fields,
    _index_lines,
    _normalize_date,
    _normalize_modules,
    _resolve_line_refs,
    parse_text_to_modules,
    verify_fields_in_original_text,
)


# ═══════════════════════════════════════════════════════════
# _index_lines
# ═══════════════════════════════════════════════════════════


def test_index_lines_adds_prefixes():
    """每行加 [n] 前缀，行号从 1 开始。"""
    indexed, lines = _index_lines("张三\nPython 工程师\n3年经验")

    assert lines == ["张三", "Python 工程师", "3年经验"]
    assert indexed == "[1] 张三\n[2] Python 工程师\n[3] 3年经验"


def test_index_lines_empty_lines_preserved():
    """空行保留（行号连续，切片还原时行数不错位）。"""
    indexed, lines = _index_lines("A\n\nB")

    assert lines == ["A", "", "B"]
    assert indexed == "[1] A\n[2] \n[3] B"


# ═══════════════════════════════════════════════════════════
# _resolve_line_refs
# ═══════════════════════════════════════════════════════════


def test_resolve_valid_ref_slices_original():
    """合法引用 → 切片原文字符串。"""
    lines = ["负责系统开发", "性能提升 30%", "团队协作"]
    result = _resolve_line_refs({"lines": [1, 2]}, lines)

    assert result == "负责系统开发\n性能提升 30%"


def test_resolve_invalid_ref_kept_for_validation():
    """越界/格式错引用 → 原样保留（交校验失败回灌重试兜底）。"""
    lines = ["A", "B", "C"]

    assert _resolve_line_refs({"lines": [1, 99]}, lines) == {"lines": [1, 99]}
    assert _resolve_line_refs({"lines": [2, 1]}, lines) == {"lines": [2, 1]}  # a > b
    assert _resolve_line_refs({"lines": [1]}, lines) == {"lines": [1]}  # 长度错
    assert _resolve_line_refs({"lines": [1, 2], "extra": 1}, lines) == {
        "lines": [1, 2],
        "extra": 1,
    }  # 非纯引用 dict 不替换


def test_coerce_non_contiguous_rich_text_line_refs():
    """模型输出三个离散行号时仍逐字还原，不触发一次昂贵 LLM 重试。"""
    modules = [
        {
            "module_type": "education",
            "content": {"items": [{"description": {"lines": [1, 3, 4]}}]},
        }
    ]

    result = _coerce_rich_text_fields(modules, ["第一行", "跳过", "第三行", "第四行"])

    assert result[0]["content"]["items"][0]["description"] == "第一行\n第三行\n第四行"


def test_coerce_contiguous_rich_text_line_range():
    """两端行号按连续区间还原，与 prompt 契约保持一致。"""
    modules = [
        {"module_type": "basic_info", "content": {"summary": {"lines": [2, 4]}}}
    ]

    result = _coerce_rich_text_fields(modules, ["标题", "A", "B", "C"])

    assert result[0]["content"]["summary"] == "A\nB\nC"


def test_resolve_nested_structure_recursive():
    """嵌套 dict/list 中引用递归替换（items[].description 场景）。"""
    lines = ["行1", "行2", "行3"]
    obj = {
        "items": [
            {"name": "项目A", "description": {"lines": [1, 2]}},
            {"name": "项目B", "description": "直接文本"},
        ]
    }
    result = _resolve_line_refs(obj, lines)

    assert result["items"][0]["description"] == "行1\n行2"
    assert result["items"][1]["description"] == "直接文本"  # 标量不受影响
    assert result["items"][0]["name"] == "项目A"


def test_resolve_scalars_and_arrays_untouched():
    """标量和普通数组原样保留。"""
    lines = ["A"]
    assert _resolve_line_refs("hello", lines) == "hello"
    assert _resolve_line_refs([1, 2, 3], lines) == [1, 2, 3]


# ═══════════════════════════════════════════════════════════
# 端到端：带 lines 引用的 LLM 输出
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_parse_with_line_refs_resolves_long_fields():
    """LLM 输出长字段用 lines 引用 → 校验通过，字段为原文切片。"""
    resume_text = "张三\nPython 工程师\n负责后端系统开发\n性能提升 30%"
    llm_response = json.dumps(
        [
            {
                "module_type": "basic_info",
                "content": {"name": "张三", "job_title": "Python 工程师"},
                "sort_order": 0,
            },
            {
                "module_type": "work_experience",
                "content": {
                    "items": [
                        {
                            "company": "某公司",
                            "position": "后端工程师",
                            "description": {"lines": [3, 4]},
                        }
                    ],
                },
                "sort_order": 1,
            },
        ]
    )

    with patch(
        "services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=llm_response
    ):
        modules = await parse_text_to_modules(resume_text)

    work = modules[1]
    assert work.content["items"][0]["description"] == "负责后端系统开发\n性能提升 30%"


@pytest.mark.asyncio
async def test_parse_line_refs_not_required():
    """LLM 不使用引用（全部字符串）→ 行为与 A2 前一致。"""
    llm_response = json.dumps(
        [
            {
                "module_type": "basic_info",
                "content": {"name": "李四", "job_title": "前端"},
                "sort_order": 0,
            },
        ]
    )

    with patch(
        "services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=llm_response
    ):
        modules = await parse_text_to_modules("李四\n前端工程师")

    assert modules[0].content["name"] == "李四"


@pytest.mark.asyncio
async def test_parse_invalid_line_ref_retries():
    """无效 lines 引用（越界）→ 校验失败回灌 → 第二次输出字符串 → 成功。"""
    bad_response = json.dumps(
        [
            {
                "module_type": "work_experience",
                "content": {
                    "items": [
                        {
                            "company": "某公司",
                            "position": "后端",
                            "description": {"lines": [1, 99]},  # 越界 → 校验失败
                        }
                    ],
                },
                "sort_order": 0,
            },
        ]
    )
    good_response = json.dumps(
        [
            {
                "module_type": "work_experience",
                "content": {
                    "items": [
                        {
                            "company": "某公司",
                            "position": "后端",
                            "description": "负责开发",
                        }
                    ],
                },
                "sort_order": 0,
            },
        ]
    )

    with patch(
        "services.rag.pipeline.llm_generate",
        new_callable=AsyncMock,
        side_effect=[bad_response, good_response],
    ):
        modules = await parse_text_to_modules("某公司\n后端\n负责开发")

    assert modules[0].content["items"][0]["description"] == "负责开发"


# ═══════════════════════════════════════════════════════════
# A2 深化：规范化 + 字段级溯源验证（借鉴 SmartResume）
# ═══════════════════════════════════════════════════════════


def test_normalize_date_formats():
    """多种日期格式统一为 YYYY-MM。"""
    assert _normalize_date("2024年9月") == "2024-09"
    assert _normalize_date("2024.3") == "2024-03"
    assert _normalize_date("2024-12") == "2024-12"
    assert _normalize_date("至今") == "至今"  # 无法识别 → 原样


def test_normalize_modules_dates_and_emails():
    """规范化流水线：日期/邮箱在 items 与顶层都生效。"""
    modules = [
        {
            "module_type": "work_experience",
            "content": {
                "items": [
                    {"company": "某公司", "position": "后端", "start_date": "2023年6月"},
                ],
            },
        },
        {
            "module_type": "basic_info",
            "content": {"name": "张三", "email": "zhangsan@qq.c0m"},
        },
    ]
    _normalize_modules(modules)

    assert modules[0]["content"]["items"][0]["start_date"] == "2023-06"
    assert modules[1]["content"]["email"] == "zhangsan@qq.com"


# ═══════════════════════════════════════════════════════════
# _clean_text_content / _is_garbled（SmartResume 输入侧规范化，直接复制）
# ═══════════════════════════════════════════════════════════


def test_clean_text_content_nfkc_and_whitespace():
    """NFKC 归一化 + 全角空格统一 + 多空格折叠（SmartResume _clean_text_content 复制验证）。"""
    from services.resume_parser import _clean_text_content

    # 全角字母 → 半角；全角空格（U+3000）→ 普通空格；NBSP → 普通空格；多空格折叠
    assert _clean_text_content("Ｐｙｔｈｏｎ　开发") == "Python 开发"
    assert _clean_text_content("后端 开发") == "后端 开发"
    assert _clean_text_content("a    b") == "a b"
    assert _clean_text_content("") == ""


def test_clean_text_content_garbled_filtered():
    """乱码长串（PDF 水印/损坏字体特征）被过滤，正常文本保留。"""
    from services.resume_parser import _clean_text_content, _is_garbled

    garbled = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW"  # 49 个全不同字符
    assert _is_garbled(garbled) is True
    assert garbled not in _clean_text_content(f"行1 {garbled} 行2")

    normal = "machine-learning-engineer-experience-2024-summer-internship"
    assert _is_garbled(normal) is False  # 有重复字符（-、e 等），唯一率 < 0.9
    assert normal in _clean_text_content(normal)

    assert _is_garbled("") is False


def test_index_lines_cleans_input_first():
    """_index_lines 前置清洗：全角/全角空格被规范化后再索引，行号对齐清洗后文本。"""
    indexed, lines = _index_lines("Ａ公司\nPython　开发")

    assert lines == ["A公司", "Python 开发"]
    assert indexed == "[1] A公司\n[2] Python 开发"


# ═══════════════════════════════════════════════════════════
# _collect_line_refs（溯源证据保留，SmartResume refer_index_range 对应物）
# ═══════════════════════════════════════════════════════════


def test_collect_line_refs_paths_and_slices():
    """行号引用在替换前被收集：字段路径 + 行号区间 + 切片原文。"""
    from services.resume_parser import _collect_line_refs

    lines = ["公司A", "负责系统开发", "维护稳定性", "项目B"]
    modules = [
        {
            "module_type": "work_experience",
            "content": {
                "items": [
                    {
                        "company": "公司A",
                        "description": {"lines": [2, 3]},  # 引用原文 2-3 行
                    }
                ]
            },
        }
    ]
    refs = _collect_line_refs(modules, lines)

    assert len(refs) == 1
    assert refs[0]["path"] == "[0].content.items[0].description"  # 顶层是模块列表 → 从 [0] 起
    assert refs[0]["lines"] == [2, 3]
    assert refs[0]["text"] == "负责系统开发\n维护稳定性"
    assert refs[0]["provenance"] == "line_ref"


def test_collect_line_refs_invalid_ignored():
    """越界/格式错误的引用不产生溯源证据（与 _resolve_line_refs 行为一致）。"""
    from services.resume_parser import _collect_line_refs

    lines = ["A", "B"]
    assert _collect_line_refs({"description": {"lines": [5, 9]}}, lines) == []
    assert _collect_line_refs({"description": {"lines": "xx"}}, lines) == []
    assert _collect_line_refs({"description": "普通文本"}, lines) == []


def test_verify_fields_provenance():
    """字段级溯源：原文包含 → verified，否则 missing。"""
    lines = ["张三", "Python 工程师", "在腾讯公司担任后端开发", "毕业于广东海洋大学"]
    modules = [
        {
            "module_type": "basic_info",
            "content": {"name": "张三", "phone": "13800138000"},
        },
        {
            "module_type": "work_experience",
            "content": {"items": [{"company": "腾讯", "position": "后端开发"}]},
        },
        {
            "module_type": "education",
            "content": {"items": [{"school": "广东海洋大学", "major": "软件工程"}]},
        },
    ]
    report = verify_fields_in_original_text(modules, lines)

    by_field = {r["field"]: r["provenance"] for r in report}
    assert by_field["name"] == "verified"
    assert by_field["phone"] == "missing"  # 原文没有手机号
    assert by_field["company"] == "verified"  # "腾讯"是"腾讯公司"子串
    assert by_field["position"] == "verified"
    assert by_field["school"] == "verified"
    assert by_field["major"] == "missing"


@pytest.mark.asyncio
async def test_parse_normalizes_dates_end_to_end():
    """端到端：LLM 输出 '2024年9月' → 校验通过且为 '2024-09'。"""
    llm_response = json.dumps(
        [
            {
                "module_type": "work_experience",
                "content": {
                    "items": [
                        {
                            "company": "某公司",
                            "position": "后端",
                            "start_date": "2024年9月",
                            "end_date": "至今",
                        }
                    ],
                },
                "sort_order": 0,
            },
        ]
    )
    with patch(
        "services.rag.pipeline.llm_generate", new_callable=AsyncMock, return_value=llm_response
    ):
        modules = await parse_text_to_modules("某公司\n后端\n2024年9月\n至今")

    assert modules[0].content["items"][0]["start_date"] == "2024-09"
