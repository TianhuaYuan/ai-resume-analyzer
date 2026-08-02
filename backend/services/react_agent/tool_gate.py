"""agent 工具闸门（T17 优化②）。

- 问候/感谢快路径：零 LLM、零工具，模板直接回复（agent1 与 builder 通用）
- 工具相关性过滤（预留，默认不启用）：按关键词裁剪传入 ReAct 的 tool schemas，
  降低 prompt 体积；因过滤错工具会断能力，仅在关键词强命中时才裁剪。

复用 agentic_rag 的问候判定，避免两处重复实现。
"""

import logging

from services.agentic_rag.rewrite import _is_trivial_greeting

logger = logging.getLogger(__name__)

# 问候模板回复（关键词 → 回复，顺序匹配）
_GREETING_REPLIES = [
    ("你好", "你好！我是你的 AI 求职助手，可以帮你分析简历、匹配 JD、模拟面试。你想从哪里开始？"),
    ("您好", "您好！我是你的 AI 求职助手，请告诉我你想了解什么。"),
    ("hi", "Hi! I'm your AI career assistant. How can I help?"),
    ("hello", "Hello! How can I help you today?"),
    ("你是谁", "我是你的 AI 求职助手，专注于简历分析、JD 匹配、面试辅导和求职策略。"),
    ("谢谢", "不客气！还有别的需要帮忙的吗？"),
    ("感谢", "不客气！随时找我。"),
    ("再见", "再见！祝你求职顺利，有需要随时回来。"),
    ("拜拜", "再见！加油～"),
    ("bye", "Goodbye! Good luck with your job search."),
]

# 兜底回复
_DEFAULT_REPLY = "你好！我是你的 AI 求职助手，有什么可以帮你？"


def is_trivial_greeting(query: str) -> bool:
    """是否极短问候/感谢（零 LLM 即可回复）。"""
    return _is_trivial_greeting(query)


def greeting_reply(query: str) -> str:
    """零 LLM 模板回复（按关键词匹配，默认兜底）。"""
    normalized = query.strip().lower().rstrip("!?！？。.")
    for key, reply in _GREETING_REPLIES:
        if key in normalized:
            return reply
    return _DEFAULT_REPLY


# ── 工具相关性过滤（保守策略）──
# 核心工具恒保留（简历检索/整文直读/深度检索/记忆召回），保证基本问答能力不断。
_CORE_TOOLS = {
    "search_resume",
    "search_assets",
    "get_resume_content",
    "answer_from_index",
    "recall_memory",
}

# 领域工具 → 触发关键词（小写匹配）。仅在强命中时保留该工具 + 核心工具。
_DOMAIN_TOOLS = {
    "jd_match": ["jd", "岗位", "招聘", "职位", "匹配", "要求"],
    "compare_resumes": ["对比", "比较", "哪个", "区别", "差异", "更好"],
    "diagnose_resume": ["诊断", "优化", "评估", "改进", "问题", "短板"],
    "interview_coach": ["面试", "考察", "提问", "准备面试", "面经"],
    "translate": ["翻译", "translate", "英文版", "日文", "英文"],
    "rewrite_star": ["star", "改写", "亮点", "包装"],
    "generate_greeting": ["打招呼", "求职信", "开场白", "hr"],
    "reply_draft": ["回复hr", "回复", "拒绝offer", "hr消息"],
    "save_memory": ["记住", "记得", "偏好", "目标", "决定"],
}


def filter_agent_tools(query: str, tool_classes: list) -> list:
    """按关键词裁剪 agent 工具集。

    安全策略：无领域关键词强命中 → 返回全量（不裁剪，绝不误杀）；
    强命中 → 返回「核心工具 + 命中领域工具」子集（prompt 体积大幅下降）。
    """
    q = query.lower()
    relevant = set(_CORE_TOOLS)
    hit = False
    for tool_name, kws in _DOMAIN_TOOLS.items():
        if any(k in q for k in kws):
            relevant.add(tool_name)
            hit = True

    if not hit:
        return tool_classes
    return [tc for tc in tool_classes if tc.name in relevant]
