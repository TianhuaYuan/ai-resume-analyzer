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
_MAX_TOKENS: int = 4000


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
- 如果某个字段在简历中没有提到，不要编造，直接省略"""


def _build_user_prompt(text: str, error_feedback: str | None = None) -> str:
    """构建用户 prompt。

    Args:
        text: 简历纯文本
        error_feedback: 上次校验的错误反馈（重试时传入）
    """
    prompt = f"请将以下简历文本解析为结构化 JSON 模块列表：\n\n---\n{text}\n---"

    if error_feedback:
        prompt += f"\n\n上次解析存在以下错误，请修正后重新输出：\n{error_feedback}"

    return prompt


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

    # 尝试找到 JSON 数组的起始和结束位置
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM 响应中未找到 JSON 数组")

    json_str = text[start : end + 1]
    parsed = json.loads(json_str)

    if not isinstance(parsed, list):
        raise ValueError(f"期望 JSON 数组，实际得到 {type(parsed).__name__}")

    return parsed


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
            errors.append(f"模块 {idx}: 未知 module_type '{module_type}'，必须是以下之一: {valid_types}")
            continue

        # 用 T22 四方契约 schema 校验 content
        try:
            validate_module_content(mt, content)
        except ValidationError as e:
            error_details = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in e.errors()
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

    errors_history: list[str] = []

    for attempt in range(_MAX_RETRIES + 1):
        # 构建 prompt（重试时带错误反馈）
        error_feedback = _build_error_feedback(errors_history) if errors_history else None
        user_prompt = _build_user_prompt(text, error_feedback)

        # 调 LLM
        try:
            response = await llm_generate(
                system=_SYSTEM_PROMPT,
                user=user_prompt,
                temperature=0.1,
                max_tokens=_MAX_TOKENS,
                user_id=user_id,
            )
        except Exception as e:
            logger.exception("LLM call failed during parse_text_to_modules (attempt %d)", attempt + 1)
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
        except (json.JSONDecodeError, ValueError) as e:
            errors_history.append(f"JSON 解析失败: {e}")
            if attempt < _MAX_RETRIES:
                logger.warning("JSON parse failed, retrying (attempt %d): %s", attempt + 1, e)
                continue
            raise ValueError(f"LLM 输出 JSON 解析失败（重试后仍失败）: {e}") from e

        # 校验模块
        validated, errors = _validate_parsed_modules(raw_modules)

        if not errors:
            # 全部校验通过
            logger.info(
                "parse_text_to_modules succeeded: attempt=%d, modules=%d",
                attempt + 1, len(validated),
            )
            return validated

        # 有校验错误
        errors_history = errors
        if attempt < _MAX_RETRIES:
            logger.warning(
                "Validation failed (attempt %d), %d errors, retrying with feedback",
                attempt + 1, len(errors),
            )
            continue

        # 重试后仍有错误，返回校验通过的部分（如果有）
        if validated:
            logger.warning(
                "parse_text_to_modules partial success: %d valid, %d invalid modules",
                len(validated), len(errors),
            )
            return validated

        # 全部失败
        error_details = _build_error_feedback(errors)
        raise ValueError(f"模块校验失败（重试后仍失败）:\n{error_details}")

    # 不应该到达这里
    raise ValueError("反解析失败：未知错误")
