"""builder 意图直达（编辑器加速，T17 优化①）。

编辑器命令明确（生成/检查/修改 X 模块），解析意图后**直接调用对应工具**，
跳过 ReAct 的「决定轮」，把一次操作从 3 轮 LLM 压到 1 次工具调用。

- 关键词快路径：零 LLM（覆盖常见「动作 + 模块」命令）
- LLM 兜底：关键词未命中时一次无工具小调用输出结构化意图
- 均失败 → 返回 None，调用方回退 ReAct 循环
"""

import json
import logging

from services.rag.pipeline import llm_generate

logger = logging.getLogger(__name__)

# 动作 → 工具
_ACTION_TO_TOOL = {
    "generate": "generate_module",
    "check": "check_module",
    "modify": "modify_module",
}

# 动作关键词（按优先级，先命中的动作生效）
_ACTION_KEYWORDS = [
    ("generate", ["生成", "帮我写", "编写", "起草", "创建", "新增", "补全"]),
    ("modify", ["修改", "改一下", "改成", "润色", "完善", "改进", "调整", "更新", "优化"]),
    ("check", ["检查", "看看", "审阅", "评估", "诊断", "建议"]),
]

# 模块中文别名 → module_type（长词优先，避免「教育背景」误命中「教育」的粗匹配）
_MODULE_ALIASES = [
    ("basic_info", ["基本信息", "基础信息", "个人信息"]),
    ("education", ["教育背景", "学历", "教育"]),
    ("work_experience", ["工作经历", "工作经验", "职业经历"]),
    ("project_experience", ["项目经历", "项目经验"]),
    ("skills", ["专业技能", "技能清单", "技术栈", "技能"]),
    ("language", ["语言能力", "外语", "语言"]),
    ("honors", ["荣誉奖项", "获奖", "荣誉"]),
    ("certificates", ["资格证书", "证书", "认证"]),
    ("interests", ["兴趣爱好", "爱好", "兴趣"]),
    ("club_activities", ["校园活动", "社团", "学生会"]),
    ("publications", ["论文专利", "论文", "出版物", "专利"]),
    ("recommendation", ["个人总结", "自我评价", "求职意向"]),
    ("social_links", ["社交链接", "社交账号"]),
]

_VALID_MODULE_TYPES = {mt for mt, _ in _MODULE_ALIASES}


def _resolve_by_keywords(query: str) -> tuple[str, dict] | None:
    """关键词快路径：返回 (tool_name, args)；无法解析返回 None。"""
    action = None
    for act, kws in _ACTION_KEYWORDS:
        if any(k in query for k in kws):
            action = act
            break
    if action is None:
        return None

    module_type = None
    for mt, aliases in _MODULE_ALIASES:
        if any(a in query for a in aliases):
            module_type = mt
            break
    if module_type is None:
        return None

    tool = _ACTION_TO_TOOL[action]
    args: dict = {"module_type": module_type}
    if tool == "generate_module":
        args["prompt"] = ""
    elif tool == "modify_module":
        args["instruction"] = query
    return tool, args


_INTENT_SYSTEM = (
    "你是简历编辑命令解析器。从用户的编辑指令中提取意图，严格输出 JSON：\n"
    '{"action": "generate|check|modify", "module_type": "<有效模块类型>", "instruction": "<修改/补充指令>"}\n'
    "有效 module_type：" + "、".join(sorted(_VALID_MODULE_TYPES)) + "\n"
    "若指令不是编辑简历模块，输出 {\"action\": \"none\"}。不要输出其他文字。"
)


async def _resolve_by_llm(query: str) -> tuple[str, dict] | None:
    """LLM 兜底：一次无工具小调用，结构化解析意图。"""
    raw = await llm_generate(
        system=_INTENT_SYSTEM,
        user=f"编辑指令：{query}",
        temperature=0.0,
        max_tokens=200,
        fallback='{"action": "none"}',
    )
    try:
        data = json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    action = data.get("action")
    if action not in _ACTION_TO_TOOL:
        return None
    module_type = data.get("module_type", "")
    if module_type not in _VALID_MODULE_TYPES:
        return None

    tool = _ACTION_TO_TOOL[action]
    args: dict = {"module_type": module_type}
    if tool == "generate_module":
        args["prompt"] = data.get("instruction", "") or ""
    elif tool == "modify_module":
        args["instruction"] = data.get("instruction", "") or query
    return tool, args


async def resolve_builder_intent(query: str) -> tuple[str, dict] | None:
    """解析 builder 编辑意图。

    Returns:
        (tool_name, args)：直接调用该工具（args 不含 resume_id，调用方补）；
        None：无法解析，回退 ReAct 循环。
    """
    keyword = _resolve_by_keywords(query)
    if keyword:
        return keyword
    try:
        return await _resolve_by_llm(query)
    except Exception as e:
        logger.warning("builder intent LLM 解析失败: %s", e)
        return None
