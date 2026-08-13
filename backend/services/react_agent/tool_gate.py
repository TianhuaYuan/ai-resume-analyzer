"""agent 工具闸门。

- 问候/感谢快路径：零 LLM、零工具，模板直接回复（agent1 与 builder 通用）
- 工具相关性过滤（保守启用）：按关键词裁剪传入 ReAct 的 tool schemas，
  降低 prompt 体积；无强命中时返回全量（绝不误杀能力），仅在强命中时裁剪。

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
# 核心工具恒保留（简历检索/整文直读/深度检索/记忆召回/子代理委派），保证基本问答能力不断。
_CORE_TOOLS = {
    "search_resume",
    "get_resume_content",
}

# 领域工具 → 触发关键词（小写匹配）。仅在强命中时保留该工具 + 核心工具。
_DOMAIN_TOOLS = {
    "search_assets": ["资产", "笔记", "资料", "历史记录", "知识库"],
    "answer_from_index": ["依据", "引用", "深入", "详细分析", "综合分析", "为什么"],
    "recall_memory": ["之前", "上次", "记得", "偏好", "长期目标"],
    "spawn": ["全面调研", "多方案", "复杂任务", "分步骤研究"],
    "jd_match": ["jd", "岗位", "招聘", "职位", "匹配", "要求"],
    "compare_resumes": ["对比", "比较", "哪个", "区别", "差异", "更好"],
    "diagnose_resume": ["诊断", "优化", "评估", "改进", "问题", "短板"],
    "interview_coach": ["面试", "考察", "提问", "准备面试", "面经"],
    "translate": ["翻译", "translate", "英文版", "日文", "英文"],
    "rewrite_star": ["star", "改写", "亮点", "包装"],
    "save_memory": ["记住", "记得", "偏好", "目标", "决定"],
    # M2: 实时岗位搜索（search_jobs_live 替代已删的 recommend_jobs 静态推荐）
    "search_jobs_live": ["招聘", "岗位", "职位", "校招", "社招", "实习", "推荐", "有哪些"],
    # A1: 通用联网搜索（面经/薪资/公司评价/招聘资讯等）
    "web_search": ["面经", "薪资", "待遇", "公司评价", "口碑", "面试经验", "招聘资讯", "行情"],
    # B3: 离线公共语料检索（面经库/题库/范文）
    "search_corpus": ["真题", "题库", "范文", "面经库", "算法题", "简历参考", "八股"],
}


def filter_agent_tools(
    query: str,
    tool_classes: list,
    *,
    tool_hint: str | None = None,
) -> list:
    """按关键词裁剪 agent 工具集。

    安全策略：无领域关键词强命中 → 返回全量（不裁剪，绝不误杀）；
    强命中 → 返回「核心工具 + 命中领域工具」子集（prompt 体积大幅下降）。
    """
    q = query.lower()
    relevant = set(_CORE_TOOLS)
    for tool_name, kws in _DOMAIN_TOOLS.items():
        if any(k in q for k in kws):
            relevant.add(tool_name)

    available_names = {tool.name for tool in tool_classes}
    if tool_hint in available_names:
        relevant.add(tool_hint)

    return [tc for tc in tool_classes if tc.name in relevant]
