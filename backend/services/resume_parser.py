"""T27: 简历文本反解析 — LLM 将纯文本解析为结构化模块。

职责：
- parse_text_to_modules: 调 LLM 将简历文本解析为 [{module_type, content, sort_order}] 列表
- pydantic 校验每个模块 content（T22 validate_module_content）
- 格式错误回灌 1 次重试（将错误信息拼入 prompt 让 LLM 修正）

设计依据：
- plan.md T27: POST /parse-to-modules（pydantic 校验 + 格式错误回灌 1 次重试）
- plan.md 风险表: 反解析/生成模块的 LLM JSON 不稳 → pydantic 校验 + 回灌重试
- T22 schema: validate_module_content 四方契约入口校验 content

重试策略：
1. 第一次调用 LLM → 解析 JSON → 逐模块 pydantic 校验
2. 如果校验失败 → 收集所有错误 → 拼入 prompt 第二次调用 LLM（回灌错误信息）
3. 第二次结果仍然校验失败 → 返回校验错误（不再重试）
4. JSON 解析失败 → 同样回灌错误重试 1 次
"""

import json
import logging
import re
import unicodedata

from pydantic import ValidationError

from schemas.resume_module import (
    ModuleType,
    ResumeModuleCreate,
    validate_module_content,
)

logger = logging.getLogger(__name__)

# 最大重试次数（回灌错误后重试 1 次）
_MAX_RETRIES: int = 1

# LLM 输出最大 token 数（简历反解析需要足够空间输出完整 JSON）
# 诊断实测确认：reasoning 模型（deepseek-v4-flash / mimo-v2.5）
# 会先消耗大量 token 思考再输出 content，4000 会被推理吃光导致 content 为空；
# 16000 实测可完整输出（推理 + JSON 约 7500 tokens），真实简历稳定反解析。
_MAX_TOKENS: int = 16000
# 实际传给 LLM 的 max_tokens：对齐 DeepSeek 推理模型 API 上限（8K），
# 超限（16000）会被 API 直接 400 拒绝 → 系统性反解析失败。实测 7500 足够。
_PARSE_MAX_TOKENS: int = min(_MAX_TOKENS, 8000)


# ═══════════════════════════════════════════════════════════
# Prompt 构建
# ═══════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """你是一个专业的简历解析助手。你的任务是将用户提供的简历纯文本解析为结构化的 JSON 模块列表。

输出格式要求：
- 输出一个 JSON 数组，每个元素是一个模块对象
- 每个模块对象包含三个字段：
  - "module_type": 模块类型（必须是以下 15 种之一）
  - "content": 模块内容（JSON 对象，结构由 module_type 决定）
  - "sort_order": 排序序号（整数，从 0 开始）

15 种 module_type 及其 content 结构：

1. basic_info（基本信息，单值）:
   content: {"name": "姓名（必填）", "phone": "手机", "email": "邮箱", "gender": "性别",
             "age": 年龄, "location": "城市", "job_title": "求职意向", "summary": "个人总结"}

2. education（教育背景，列表）:
   content: {"items": [{"school": "学校（必填）", "degree": "学历", "major": "专业",
             "start_date": "2021-09", "end_date": "2025-06", "gpa": 3.8, "description": "说明"}]}

3. work_experience（工作经历，列表）:
   content: {"items": [{"company": "公司（必填）", "position": "职位（必填）",
             "start_date": "2023-06", "end_date": "2024-09",
             "description": "工作描述", "achievements": ["成就1", "成就2"]}]}

4. project_experience（项目经历，列表）:
   content: {"items": [{"name": "项目名（必填）", "role": "角色",
             "start_date": "2023-01", "end_date": "2023-06",
             "url": "链接", "description": "描述", "tech_stack": ["Python", "FastAPI"]}]}

5. skills（专业技能，列表）:
   content: {"items": [{"name": "技能名（必填）", "level": 3, "category": "分类"}]}

6. language（语言能力，列表）:
   content: {"items": [{"name": "英语（必填）", "proficiency": "流利", "score": "CET-6"}]}

7. honors（荣誉奖项，列表）:
   content: {"items": [{"title": "奖项名（必填）", "date": "2024-05", "description": "说明"}]}

8. certificates（证书，列表）:
   content: {"items": [{"name": "证书名（必填）", "issuer": "颁发机构", "date": "2024-01", "score": "95"}]}

9. interests（兴趣爱好，列表）:
   content: {"items": [{"name": "阅读"}, {"name": "编程"}, {"name": "篮球"}]}

10. club_activities（社团活动，列表）:
    content: {"items": [{"name": "社团名（必填）", "role": "角色",
              "start_date": "2022-09", "end_date": "2023-06", "description": "描述"}]}

11. publications（研究成果，列表）:
    content: {"items": [{"title": "论文标题（必填）", "authors": ["作者1"],
              "venue": "期刊", "date": "2024-03", "url": "链接"}]}

12. recommendation（推荐人，列表）:
    content: {"items": [{"name": "推荐人姓名（必填）", "title": "职位",
              "organization": "组织", "contact": "联系方式", "email": "邮箱"}]}

13. social_links（社交链接）:
    content: {"items": [{"platform": "GitHub", "url": "URL"}, {"platform": "LinkedIn", "url": "URL"}]}

14. other（其他，单值）:
    content: {"title": "段落标题", "content": "内容文本（必填）"}

15. custom（自定义，单值）:
    content: {"title": "模块标题（必填）", "content": "内容文本（必填）"}

注意事项：
- 只输出 JSON 数组，不要添加任何解释性文字
- 简历中不存在的模块不要输出
- sort_order 按模块在简历中出现的顺序从 0 递增
- 日期格式统一为 "YYYY-MM"
- 如果某个字段在简历中没有提到，不要编造，直接省略

【长文本字段优化（A2，借鉴 SmartResume 索引指针机制）】
输入文本每行带 [行号] 前缀（如 "[3] 负责xx系统的开发"）。
对于长文本字段（description / achievements 的元素 / summary / content），
可以省略完整原文，只引用原文行号区间，格式：{"lines": [开始行, 结束行]}。
例如某工作描述对应原文第 10-12 行，输出 "description": {"lines": [10, 12]}。
规则：
- 只在字段值确实与原文行内容一致时使用引用；需要改写/提炼时仍输出字符串
- 引用必须真实指向原文行号，禁止编造行号
- 其余字段（日期/公司/技能名等短字段）一律输出字符串，不要用 lines"""


# 乱码串正则（PDF 水印/损坏字体的长字母数字串特征，来自 SmartResume should_remove）
_GARBLED_PATTERN = re.compile(r"[a-zA-Z0-9\-~_]{40,}")


def _is_garbled(s: str) -> bool:
    """乱码判定（SmartResume should_remove 的无 tiktoken 等价）。

    SmartResume 用 BPE token 数 > 字符数*0.5 判定（乱码每个字符一个 token）。
    本项目不引 tiktoken，用「唯一字符率 ≥ 0.9」近似：正常英文/URL 串的字符重复率
    通常 < 0.9，而随机乱码串几乎每个字符都不同。
    """
    if not s:
        return False
    return len(set(s)) / len(s) >= 0.9


def _clean_text_content(text: str) -> str:
    """输入侧文本规范化（直接复制 SmartResume data_processor._clean_text_content，Apache-2.0）。

    与 SmartResume 一致的三步：
    1. NFKC 归一化（全角→半角，兼容字符统一）
    2. 空白字符统一为普通空格（含全角空格 U+3000 / NBSP U+00A0 / 狭义空白 U+2000-U+200A 等）
    3. 连续空格折叠 + 乱码长串过滤（PDF 水印/损坏字体的长字母数字串）

    前置到 _index_lines 之前：保证行号索引与 LLM 引用基于清洗后文本，
    行数不变（NFKC/空白折叠不改行数），行号索引安全。
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)

    text = re.sub(
        r"[ \u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\u00A7]",
        " ",
        text,
    )

    text = re.sub(r" {2,}", " ", text)

    text = re.sub(
        _GARBLED_PATTERN,
        lambda m: "" if _is_garbled(m.group(0)) else m.group(0),
        text,
    )
    return text


def _index_lines(text: str) -> tuple[str, list[str]]:
    """给简历文本每行加 [行号] 前缀（A2 索引指针机制）。

    A2 深化（SmartResume 对照）：输入侧先经 _clean_text_content 规范化
    （NFKC/空白统一/乱码过滤），再切行索引——LLM 引用的行内容即清洗后原文。

    Args:
        text: 简历纯文本

    Returns:
        (带行号文本, 原文行列表) —— 行号从 1 开始，
        后处理用原文行列表把 LLM 的 {"lines": [a, b]} 引用切片还原
    """
    text = _clean_text_content(text)
    lines = text.split("\n")
    indexed = "\n".join(f"[{i + 1}] {line}" for i, line in enumerate(lines))
    return indexed, lines


def _build_user_prompt(text: str, error_feedback: str | None = None) -> str:
    """构建用户 prompt。

    Args:
        text: 简历纯文本（A2 起为带 [行号] 前缀的索引文本）
        error_feedback: 上次校验的错误反馈（重试时传入）
    """
    prompt = f"请将以下简历文本解析为结构化 JSON 模块列表：\n\n---\n{text}\n---"

    if error_feedback:
        prompt += f"\n\n上次解析存在以下错误，请修正后重新输出：\n{error_feedback}"

    return prompt


def _resolve_line_refs(obj, lines: list[str]):
    """解析 LLM 输出中的 {"lines": [a, b]} 引用，切片替换为原文（A2）。

    指针引用出现在字段值位置（如 content 的 description），
    递归遍历返回**替换后的新对象**（不修改原对象）：
    - dict 恰好为 {"lines": [a, b]} 且行号合法 → 替换为原文切片字符串
    - 其他 dict / list / 标量 → 递归保留
    引用无效（越界/格式错）→ 原样保留 {"lines": [...]}，
    由上层 pydantic 校验失败回灌重试兜底。

    Args:
        obj: LLM 输出的模块原始字典
        lines: 原文行列表（_index_lines 返回值，行号从 1 起）
    """
    if isinstance(obj, dict):
        if set(obj.keys()) == {"lines"} and isinstance(obj.get("lines"), list):
            ref = obj["lines"]
            if len(ref) == 2 and isinstance(ref[0], int) and isinstance(ref[1], int):
                a, b = ref
                if 1 <= a <= b <= len(lines):
                    return "\n".join(lines[a - 1 : b])
        return {k: _resolve_line_refs(v, lines) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_line_refs(item, lines) for item in obj]
    return obj


def _collect_line_refs(obj, lines: list[str], path: str = "") -> list[dict]:
    """收集 LLM 行号引用（SmartResume refer_index_range 保留的对应物，A2 深化）。

    _resolve_line_refs 把 {"lines"} 替换为字符串后引用信息即丢失，
    故在替换前调用本函数收集溯源证据：字段路径 + 行号区间 + 切片原文。
    供 E1 可溯源诊断展示「字段 ↔ 原文行号区间」双向可查（SmartResume 保留
    refer_index_range 字段的等价实现）。

    Args:
        obj: LLM 输出的模块原始字典（未做 lines 替换）
        lines: 原文行列表（行号从 1 起）
        path: 当前字段路径（如 "content.items[0].description"）

    Returns:
        [{path, lines: [a, b], text, provenance: "line_ref"}]
    """
    out: list[dict] = []
    if isinstance(obj, dict):
        if set(obj.keys()) == {"lines"} and isinstance(obj.get("lines"), list):
            ref = obj["lines"]
            if len(ref) == 2 and isinstance(ref[0], int) and isinstance(ref[1], int):
                a, b = ref
                if 1 <= a <= b <= len(lines):
                    out.append(
                        {
                            "path": path or "<root>",
                            "lines": [a, b],
                            "text": "\n".join(lines[a - 1 : b]),
                            "provenance": "line_ref",
                        }
                    )
        for key, value in obj.items():
            out.extend(_collect_line_refs(value, lines, f"{path}.{key}" if path else str(key)))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            out.extend(_collect_line_refs(item, lines, f"{path}[{i}]"))
    return out


def _build_error_feedback(errors: list[str]) -> str:
    """将校验错误列表构建为反馈文本。"""
    return "\n".join(f"- {err}" for err in errors)


# ═══════════════════════════════════════════════════════════
# JSON 解析
# ═══════════════════════════════════════════════════════════


def _extract_json_from_response(response: str) -> list[dict]:
    """从 LLM 响应中提取 JSON 数组。

    LLM 可能输出：
    - 纯 JSON 数组
    - ```json ... ``` 包裹的 JSON
    - 带前后解释文字的 JSON

    Returns:
        解析后的模块字典列表

    Raises:
        json.JSONDecodeError: JSON 解析失败
        ValueError: 响应不是 JSON 数组
    """
    text = response.strip()

    # 尝试提取 ```json ... ``` 代码块
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1).strip()

    # 找到 JSON 数组的起始位置
    start = text.find("[")
    if start == -1:
        raise ValueError("LLM 响应中未找到 JSON 数组")

    # 从后往前找第一个能完整解析的 "]"（抗截断）：
    # 输出被 max_tokens 截断时，rfind("]") 可能命中嵌套数组（如 tech_stack 内）的 "]",
    # 导致 json.loads 失败。逐个候选位置尝试，取最靠后且能完整解析的 JSON 数组。
    search_end = len(text) - 1
    while search_end > start:
        end = text.rfind("]", 0, search_end + 1)
        if end == -1 or end <= start:
            break
        json_str = text[start : end + 1]
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            search_end = end - 1
            continue
        if isinstance(parsed, list):
            return parsed
        # 解析成功但不是数组 → 继续往前找
        search_end = end - 1

    # 所有候选位置都失败：若 text[start:] 是非法 JSON，触发 JSONDecodeError
    # （与旧逻辑异常类型一致，保持测试契约）；否则抛 ValueError。
    _ = json.loads(text[start:])  # noqa: B018 — 仅用于触发异常
    raise ValueError("LLM 响应中未找到 JSON 数组")


# ═══════════════════════════════════════════════════════════
# A2 深化：规范化流水线（借鉴 alibaba/SmartResume data_processor.py）
# ═══════════════════════════════════════════════════════════

# 日期格式：YYYY年M月 / YYYY.M / YYYY-MM → YYYY-MM
_DATE_PATTERN = re.compile(r"^(\d{4})\s*[年.\-/]\s*(\d{1,2})\s*月?$")

# OCR 常见混淆纠错（SmartResume _clean_email 机制）
_EMAIL_TYPO_FIXES = [
    (re.compile(r"\.c0m(\s|$|\")"), ".com\\1"),
    (re.compile(r"gmai1\.", re.IGNORECASE), "gmail."),
    (re.compile(r"qq\.c0m"), "qq.com"),
]


def _normalize_date(value: str) -> str:
    """日期规范化：'2024年9月' → '2024-09'（SmartResume _normalize_date 机制）。

    无法识别的格式原样返回（避免破坏 pydantic 校验 → 触发回灌重试）。
    """
    if not isinstance(value, str):
        return value
    match = _DATE_PATTERN.match(value.strip())
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    return value.strip()


def _normalize_email(value: str) -> str:
    """邮箱 OCR 混淆纠错（c0m→com 等）。"""
    if not isinstance(value, str):
        return value
    result = value.strip()
    for pattern, repl in _EMAIL_TYPO_FIXES:
        result = pattern.sub(repl, result)
    return result


def _normalize_text_field(value, field_key: str):
    """按字段类型规范化单个值（日期/邮箱），其余原样。"""
    if not isinstance(value, str):
        return value
    if "date" in field_key or field_key in ("start_date", "end_date"):
        return _normalize_date(value)
    if "email" in field_key or field_key == "email":
        return _normalize_email(value)
    return value


def _normalize_modules(raw_modules: list[dict]) -> list[dict]:
    """规范化 LLM 输出（A2 深化，借鉴 SmartResume 规范化阶段）。

    在 pydantic 校验前原地规范化 content 中的日期（"2024年9月" → "2024-09"）
    与邮箱（OCR 混淆纠错），避免非标准格式污染后续评分/JD 匹配。

    Args:
        raw_modules: LLM 输出的原始模块字典列表（原地修改）

    Returns:
        同一列表（便于链式调用）
    """
    for module in raw_modules:
        content = module.get("content")
        if not isinstance(content, dict):
            continue
        # 顶层字段 + items 列表里的条目
        targets: list[dict] = [content]
        for value in content.values():
            if isinstance(value, list):
                targets.extend(item for item in value if isinstance(item, dict))

        for target in targets:
            for key, value in list(target.items()):
                if isinstance(value, str):
                    target[key] = _normalize_text_field(value, key)
                elif isinstance(value, list) and key in ("achievements", "tech_stack"):
                    # 列表内字符串元素规范化（如日期出现在 achievements 描述里）
                    target[key] = [
                        _normalize_text_field(item, key) if isinstance(item, str) else item
                        for item in value
                    ]
    return raw_modules


def verify_fields_in_original_text(modules: list[dict], original_lines: list[str]) -> list[dict]:
    """A2 深化：字段级溯源验证（借鉴 SmartResume _validate_fields_in_text）。

    对关键短字段（姓名/手机/公司/岗位/学校/专业）做规范化包含检查——
    必须在原文中出现（substring 匹配），否则标记 provenance="missing"。

    不做删除（避免破坏 schema 校验），返回报告供诊断/日志使用；
    完整接入 E1 可溯源诊断展示。

    Args:
        modules: 规范化后的原始模块字典列表（读取用）
        original_lines: 原文行列表

    Returns:
        report: [{module_type, field, value, provenance: "verified"|"missing"}]
    """
    import unicodedata

    def _norm(s: str) -> str:
        """NFKC + 去空白/标点，用于宽松包含匹配。"""
        return re.sub(
            r"[\s，。、,.;;：:（）()\[\]【】\"'“”\-–—_]+", "", unicodedata.normalize("NFKC", s)
        )

    corpus = _norm("\n".join(original_lines))

    # 需要验证的字段映射：module_type → (key 路径, 取值函数)
    def _verify_text(value) -> bool:
        if not value or not isinstance(value, str):
            return False
        return _norm(value) in corpus

    report: list[dict] = []
    for module in modules:
        module_type = module.get("module_type")
        content = module.get("content")
        if not isinstance(content, dict):
            continue

        checks: list[tuple[str, str]] = []
        if module_type == "basic_info":
            checks = [("name", content.get("name", "")), ("phone", content.get("phone", ""))]
        elif module_type == "work_experience":
            for item in content.get("items", []) or []:
                if isinstance(item, dict):
                    checks.extend(
                        [
                            ("company", item.get("company", "")),
                            ("position", item.get("position", "")),
                        ]
                    )
        elif module_type == "education":
            for item in content.get("items", []) or []:
                if isinstance(item, dict):
                    checks.extend(
                        [
                            ("school", item.get("school", "")),
                            ("major", item.get("major", "")),
                        ]
                    )

        for field, value in checks:
            if not value:
                continue
            report.append(
                {
                    "module_type": module_type,
                    "field": field,
                    "value": value,
                    "provenance": "verified" if _verify_text(value) else "missing",
                }
            )
    return report


# ═══════════════════════════════════════════════════════════
# 模块校验
# ═══════════════════════════════════════════════════════════


def _validate_parsed_modules(
    raw_modules: list[dict],
) -> tuple[list[ResumeModuleCreate], list[str]]:
    """校验解析后的模块列表。

    Args:
        raw_modules: LLM 输出的原始模块字典列表

    Returns:
        (validated_modules, errors)
        - validated_modules: 校验通过的模块列表
        - errors: 校验失败的错误信息列表
    """
    validated: list[ResumeModuleCreate] = []
    errors: list[str] = []

    for idx, raw in enumerate(raw_modules):
        if not isinstance(raw, dict):
            errors.append(f"模块 {idx}: 不是有效的 JSON 对象")
            continue

        module_type = raw.get("module_type")
        content = raw.get("content")
        sort_order = raw.get("sort_order", idx)

        if not module_type:
            errors.append(f"模块 {idx}: 缺少 module_type 字段")
            continue

        if not isinstance(content, dict):
            errors.append(f"模块 {idx} ({module_type}): content 不是有效的 JSON 对象")
            continue

        # 校验 module_type 是否在 15 种枚举中
        try:
            mt = ModuleType(module_type)
        except ValueError:
            valid_types = ", ".join(mt.value for mt in ModuleType)
            errors.append(
                f"模块 {idx}: 未知 module_type '{module_type}'，必须是以下之一: {valid_types}"
            )
            continue

        # 用 T22 四方契约 schema 校验 content
        try:
            validate_module_content(mt, content)
        except ValidationError as e:
            error_details = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
            )
            errors.append(f"模块 {idx} ({module_type}): {error_details}")
            continue
        except ValueError as e:
            errors.append(f"模块 {idx} ({module_type}): {e}")
            continue

        # 校验通过，构建 ResumeModuleCreate
        validated.append(
            ResumeModuleCreate(
                module_type=mt,
                content=content,
                sort_order=sort_order if isinstance(sort_order, int) and sort_order >= 0 else idx,
            )
        )

    return validated, errors


# ═══════════════════════════════════════════════════════════
# 主反解析入口
# ═══════════════════════════════════════════════════════════


async def parse_text_to_modules(
    text: str,
    user_id: int | None = None,
) -> list[ResumeModuleCreate]:
    """将简历纯文本反解析为结构化模块列表。

    流程：
    1. 调 LLM 解析文本 → JSON 数组
    2. 逐模块 pydantic 校验（T22 validate_module_content）
    3. 校验失败 → 回灌错误信息重试 1 次
    4. 重试后仍失败 → 抛异常

    Args:
        text: 简历纯文本
        user_id: 用户 ID（传入时记录 LLM usage）

    Returns:
        校验通过的模块列表

    Raises:
        ValueError: 文本为空 / LLM 输出无法解析 / 校验失败（重试后仍失败）
    """
    if not text or not text.strip():
        raise ValueError("简历文本不能为空")

    from services.rag.pipeline import llm_generate

    # A2: 行号索引（SmartResume 索引指针机制）——LLM 可引用行号而非重写长文本
    indexed_text, original_lines = _index_lines(text)

    errors_history: list[str] = []

    for attempt in range(_MAX_RETRIES + 1):
        # 构建 prompt（重试时带错误反馈）
        error_feedback = _build_error_feedback(errors_history) if errors_history else None
        user_prompt = _build_user_prompt(indexed_text, error_feedback)

        # 调 LLM（传输/超时错误经 with_retry 指数退避重试，避免一次失败就整个物化失败；
        # temperature 传 None（不传给 API）规避推理模型对 temperature 参数的 400 拒绝）
        try:
            from core.retry import RetryBudget, with_retry

            response = await with_retry(
                llm_generate,
                system=_SYSTEM_PROMPT,
                user=user_prompt,
                temperature=None,
                max_tokens=_PARSE_MAX_TOKENS,
                user_id=user_id,
                budget=RetryBudget(max_retries=2, base_delay=1.5, timeout=90),
            )
        except Exception as e:
            logger.exception(
                "LLM call failed during parse_text_to_modules (attempt %d)", attempt + 1
            )
            raise ValueError(f"LLM 调用失败: {e}") from e

        if not response or not response.strip():
            errors_history.append("LLM 返回空响应")
            if attempt < _MAX_RETRIES:
                logger.warning("Empty LLM response, retrying (attempt %d)", attempt + 1)
                continue
            raise ValueError("LLM 返回空响应，反解析失败")

        # 解析 JSON
        try:
            raw_modules = _extract_json_from_response(response)
            # A2 深化: 规范化（日期/邮箱）→ 指针引用切片 → 校验
            raw_modules = _normalize_modules(raw_modules)
            # A2 深化: 溯源证据保留——行号引用在替换前收集（SmartResume refer_index_range 对应物）
            line_refs = _collect_line_refs(raw_modules, original_lines)
            raw_modules = _resolve_line_refs(raw_modules, original_lines)
            # A2 深化: 字段级溯源验证（缺失字段记日志，供 E1 诊断展示）
            provenance_report = verify_fields_in_original_text(raw_modules, original_lines)
            if line_refs:
                provenance_report.extend(line_refs)
                logger.info("解析行号引用（溯源证据）: %d 个", len(line_refs))
            missing = [r for r in provenance_report if r["provenance"] == "missing"]
            if missing:
                logger.warning(
                    "解析字段未在原文中找到（%d 个）: %s",
                    len(missing),
                    [f"{r['module_type']}.{r['field']}" for r in missing],
                )
        except (json.JSONDecodeError, ValueError) as e:
            errors_history.append(f"JSON 解析失败: {e}")
            if attempt < _MAX_RETRIES:
                logger.warning("JSON parse failed, retrying (attempt %d): %s", attempt + 1, e)
                continue
            raise ValueError(f"LLM 输出 JSON 解析失败（重试后仍失败）: {e}") from e

        # 校验模块
        validated, errors = _validate_parsed_modules(raw_modules)

        if not errors:
            if not validated:
                # LLM 返回空数组 [] → 不是合法结果，视为失败回灌重试，
                # 避免上层（materialize / parse-to-modules）把"失败"误当"成功空结果"。
                errors_history.append("LLM 返回空数组，未解析出任何模块")
                if attempt < _MAX_RETRIES:
                    logger.warning("Empty module list from LLM, retrying (attempt %d)", attempt + 1)
                    continue
                raise ValueError("未解析出任何模块（LLM 返回空数组）")
            # 全部校验通过
            logger.info(
                "parse_text_to_modules succeeded: attempt=%d, modules=%d",
                attempt + 1,
                len(validated),
            )
            return validated

        # 有校验错误
        errors_history = errors
        if attempt < _MAX_RETRIES:
            logger.warning(
                "Validation failed (attempt %d), %d errors, retrying with feedback",
                attempt + 1,
                len(errors),
            )
            continue

        # 重试后仍有错误，返回校验通过的部分（如果有）
        if validated:
            logger.warning(
                "parse_text_to_modules partial success: %d valid, %d invalid modules",
                len(validated),
                len(errors),
            )
            return validated

        # 全部失败
        error_details = _build_error_feedback(errors)
        raise ValueError(f"模块校验失败（重试后仍失败）:\n{error_details}")

    # 不应该到达这里
    raise ValueError("反解析失败：未知错误")
