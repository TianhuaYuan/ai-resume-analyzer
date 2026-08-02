"""T14/T15: memory 装配 + L3 画像构建钩子。

三层记忆架构：
- L1 工作记忆：当前循环 messages，16k token 预算逐出（先丢最旧工具轮 → 再丢最旧对话轮）
- L2 情景记忆：qa_history 取最近 10 条
- L3 语义记忆：Redis 缓存的 summary+skills 紧凑画像（不调 get_full_analysis 四连发）

L3 画像构建钩子（T15）：
- ready 转换共享点后台构建（上传 + builder 双路径）
- 只调 summary + skills 两种分析类型（2 次 LLM，不调全量 4 种）
- 不阻塞热路径，错误不外抛

决策依据：spec A#11/#12, B 层四层记忆表。
"""

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from models.qa_history import QAHistory
from services.analyze_service import analyze_resume
from services.resume_analysis_cache import get_analysis_cache

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────
MAX_TOOL_RESULT_CHARS = 2000
DEFAULT_L1_BUDGET = 16000
DEFAULT_KEEP_LAST_ROUNDS = 4
DEFAULT_L2_LIMIT = 10


# ═══════════════════════════════════════════════════════════════
# 工具结果截断
# ═══════════════════════════════════════════════════════════════


def truncate_tool_result(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """截断工具结果到 ≤ max_chars 字符，超长部分用 ... 省略。"""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # 留 3 字符给省略号
    return text[: max_chars - 3] + "..."


# ═══════════════════════════════════════════════════════════════
# Token 估算
# ═══════════════════════════════════════════════════════════════


def estimate_tokens(text: str) -> int:
    """粗略估算文本 token 数。

    中文约 2 字符/token，英文约 4 字符/token。
    不依赖 tiktoken，避免额外依赖 + 启动开销。
    """
    if not text:
        return 0
    cn_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    en_chars = len(text) - cn_chars
    # 中文 2 字符/token，英文 4 字符/token，至少 1
    return max(1, cn_chars // 2 + en_chars // 4)


def count_message_tokens(messages: list[dict]) -> int:
    """计算消息列表的总 token 估算值。"""
    if not messages:
        return 0
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        if isinstance(content, str):
            total += estimate_tokens(content)
        # tool_calls 的 arguments 也算
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                total += estimate_tokens(func.get("arguments", ""))
                total += estimate_tokens(func.get("name", ""))
    return total


# ═══════════════════════════════════════════════════════════════
# L1 工作记忆：逐出管理
# ═══════════════════════════════════════════════════════════════


def _split_rounds(messages: list[dict]) -> tuple[list[dict], list[list[dict]]]:
    """将消息列表拆分为 (system_msgs, rounds)。

    每轮以 user 消息开头，包含后续非 user 消息直到下一个 user。
    system 消息单独提取，始终保留。
    """
    system_msgs = []
    rounds: list[list[dict]] = []
    current_round: list[dict] = []

    for msg in messages:
        if msg.get("role") == "system":
            system_msgs.append(msg)
            continue
        if msg.get("role") == "user" and current_round:
            rounds.append(current_round)
            current_round = []
        current_round.append(msg)

    if current_round:
        rounds.append(current_round)

    return system_msgs, rounds


def _is_tool_round(round_msgs: list[dict]) -> bool:
    """判断是否为工具轮（含 tool 角色消息）。"""
    return any(m.get("role") == "tool" for m in round_msgs)


def manage_l1_context(
    messages: list[dict],
    max_tokens: int = DEFAULT_L1_BUDGET,
    keep_last_rounds: int = DEFAULT_KEEP_LAST_ROUNDS,
) -> list[dict]:
    """L1 工作记忆管理：16k token 预算逐出。

    逐出优先级：
    1. 先截断所有工具结果到 ≤2000 字符
    2. 超额时先丢最旧工具轮
    3. 再丢最旧对话轮
    4. 始终保留 system 消息和最近 keep_last_rounds 轮
    """
    if not messages:
        return []

    # 深拷贝避免修改原列表
    result = []
    for msg in messages:
        copied = dict(msg)
        # 1. 截断所有工具结果
        if copied.get("role") == "tool" and copied.get("content"):
            copied["content"] = truncate_tool_result(copied["content"])
        result.append(copied)

    # 2. 检查是否需要逐出
    if count_message_tokens(result) <= max_tokens:
        return result

    # 3. 拆分轮次
    system_msgs, rounds = _split_rounds(result)

    # 可逐出的轮次索引范围：[0, len(rounds) - keep_last_rounds)
    max_evictable = len(rounds) - keep_last_rounds
    if max_evictable <= 0:
        # 没有可逐出的轮次，直接返回（截断后的）
        return result

    evicted = True
    while evicted and count_message_tokens(system_msgs + [m for r in rounds for m in r]) > max_tokens:
        evicted = False

        # 优先丢最旧的工具轮
        for i in range(min(max_evictable, len(rounds))):
            if _is_tool_round(rounds[i]):
                logger.debug("L1 逐出工具轮 #%d", i)
                rounds.pop(i)
                max_evictable = min(max_evictable, len(rounds) - keep_last_rounds)
                if max_evictable < 0:
                    max_evictable = 0
                evicted = True
                break

        if evicted:
            continue

        # 没有工具轮可丢，丢最旧对话轮
        if max_evictable > 0 and len(rounds) > keep_last_rounds:
            logger.debug("L1 逐出对话轮 #0")
            rounds.pop(0)
            max_evictable = min(max_evictable, len(rounds) - keep_last_rounds)
            if max_evictable < 0:
                max_evictable = 0
            evicted = True

    return system_msgs + [msg for round_msgs in rounds for msg in round_msgs]


# ═══════════════════════════════════════════════════════════════
# L2 情景记忆：qa_history 最近 10 条
# ═══════════════════════════════════════════════════════════════


async def get_l2_history(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    limit: int = DEFAULT_L2_LIMIT,
) -> list[dict]:
    """从 qa_history 取最近 limit 条问答，按时间倒序。

    返回 [{"question": ..., "answer": ...}, ...]
    """
    result = await db.execute(
        select(QAHistory)
        .where(
            QAHistory.user_id == user_id,
            QAHistory.resume_id == resume_id,
            QAHistory.status == "complete",  # 只取已完成问答，过滤中断空记录
        )
        .order_by(QAHistory.created_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()
    return [{"question": r.question, "answer": r.answer} for r in records]


# ═══════════════════════════════════════════════════════════════
# L3 语义记忆：Redis 缓存的 summary+skills 紧凑画像
# ═══════════════════════════════════════════════════════════════


async def get_l3_profile(resume_id: int) -> dict | None:
    """从 Redis 缓存读 L3 紧凑画像（summary + skills）。

    复用 analyze_service 产出的 Redis 缓存，不调 get_full_analysis 四连发。
    只取 summary + skills 两种，experience/score 留给 diagnose_resume 工具按需调。

    Returns:
        {"summary": str, "skills": list[str]} 或 None（完全无缓存时）
        部分命中时返回部分画像。
    """
    summary_cache = await get_analysis_cache(resume_id, "summary")
    skills_cache = await get_analysis_cache(resume_id, "skills")

    profile: dict = {}

    if summary_cache is not None:
        # 缓存结构可能是 {"summary": ...} 或 {"analysis": ...}
        profile["summary"] = summary_cache.get("summary") or summary_cache.get("analysis", "")

    if skills_cache is not None:
        # skills 缓存可能是 {"skills": [...]} 或 {"analysis": ...}
        skills = skills_cache.get("skills")
        if skills is None:
            # 如果只有 analysis 文本，作为单元素列表
            analysis_text = skills_cache.get("analysis", "")
            if analysis_text:
                skills = [analysis_text]
        if skills:
            profile["skills"] = skills

    if not profile:
        return None

    return profile


# ═══════════════════════════════════════════════════════════════
# System Prompt 装配
# ═══════════════════════════════════════════════════════════════

_BASE_INSTRUCTIONS = """\
# 角色定位
你是一个专业的简历助手 Agent，帮助用户分析简历、匹配岗位、改写优化、模拟面试。

# 行为准则
1. **禁止编造**：不要虚构简历中不存在的信息。如果工具返回的数据不足，明确告知用户。
2. **工具优先**：需要检索简历内容时，优先调用工具而非凭记忆回答。
3. **简洁高效**：回答直击要点，避免冗长。工具调用后整合结果给出结构化回答。
4. **归属隔离**：只能访问当前用户的简历，不要泄露其他用户数据。
5. **工具参数**：所有需要 resume_id 的工具必须使用下方「当前简历」中给出的 ID，禁止猜测或编造 ID。
   如果用户提到的简历不在当前列表中，明确说明无法访问。

# 输出格式
- 分析类回答用 Markdown 结构化（标题 + 列表）。
- 评分类回答给出具体分数和依据。
- 改写/翻译类回答：调用工具写入模块草稿后，简要说明已写入哪些模块，并引导用户到「编辑」页查看调整。
"""

# builder 模式（/ask/builder）使用独立指令：用户在编辑器里让 AI 生成/优化/重写模块。
# 与 QA 模式不同，这里允许按用户明确要求直接生成内容（含示例/占位符）并写入模块，
# 简历内容由用户最终负责。QA 模式的"禁止编造"准则不适用于此场景。
_BUILDER_INSTRUCTIONS = """\
# 角色定位
你是简历编辑助手 Agent，帮助用户在编辑器中生成、优化、重写简历模块内容，并回填到表单。

# 行为准则
1. **内容生成**：用户明确要求生成或回填内容时，直接生成模块内容并调用工具写入，无需等待用户补全信息。可生成示例/占位内容，简历内容由用户最终负责。
2. **工具优先**：写入/修改模块必须调用对应工具（generate_module / modify_module / rewrite_resume）提交，而非仅输出文字。
3. **简洁高效**：回答直击要点，工具调用后简要告知已写入哪个模块。
4. **归属隔离**：只能访问当前用户的简历。
5. **工具参数**：使用「当前简历」中给出的 resume_id，禁止猜测。

# 输出格式
- 调用工具写入模块后，简要说明已写入/更新了哪些模块。
- 需要用户补充的关键信息用列表列出，但不要因此阻塞工具写入。
"""


async def assemble_system_prompt(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    *,
    builder: bool = False,
    query: str | None = None,
) -> str:
    """装配 system prompt：基础指令 + 当前简历上下文 + L3 画像 + L2 历史。

    Args:
        builder: True 时用 builder 专属指令（允许按用户要求生成内容），
                 False 用通用指令（QA 分析，禁止编造简历事实）。

    分段标记用 # 标题，便于 LLM 理解结构。
    """
    sections: list[str] = [_BUILDER_INSTRUCTIONS if builder else _BASE_INSTRUCTIONS]
    _t0 = time.perf_counter()

    # #4: 注入当前简历上下文（ID/文件名/状态），防止 LLM 猜错 resume_id 导致"无权访问"
    from models.resume import Resume

    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    current_resume = resume_result.scalar_one_or_none()
    _resume_ms = round((time.perf_counter() - _t0) * 1000)
    _t1 = time.perf_counter()
    if current_resume is not None:
        resume_ctx = [
            "\n# 当前简历",
            f"ID: {current_resume.id}",
            f"文件名: {current_resume.filename}",
            f"状态: {current_resume.status}",
        ]
        if current_resume.status == "draft":
            resume_ctx.append(
                "（草稿未完成：检索/诊断/匹配类工具可能不可用，请提示用户先在编辑器中「保存并完成」）"
            )
        sections.append("\n".join(resume_ctx))
    else:
        sections.append(
            "\n# 当前简历\n（无法访问该简历，请明确告知用户无权访问或简历不存在）"
        )

    # L3 画像
    l3_profile = await get_l3_profile(resume_id)
    _l3_ms = round((time.perf_counter() - _t1) * 1000)
    _t2 = time.perf_counter()
    if l3_profile:
        profile_parts = ["\n# 简历画像（L3 语义记忆）"]
        if "summary" in l3_profile:
            profile_parts.append(f"**总结**：{l3_profile['summary']}")
        if "skills" in l3_profile:
            skills_text = "、".join(l3_profile["skills"]) if isinstance(l3_profile["skills"], list) else str(l3_profile["skills"])
            profile_parts.append(f"**技能**：{skills_text}")
        sections.append("\n".join(profile_parts))

    # L2 历史
    l2_history = await get_l2_history(db, user_id, resume_id)
    _l2_ms = round((time.perf_counter() - _t2) * 1000)
    if l2_history:
        history_parts = ["\n# 历史问答（L2 情景记忆）"]
        for i, qa in enumerate(l2_history, 1):
            history_parts.append(f"{i}. Q: {qa['question']}")
            history_parts.append(f"   A: {qa['answer'][:200]}")
        sections.append("\n".join(history_parts))

    # L4 长期语义记忆（T15）：按当前问题语义召回，注入 system prompt（跨会话一致性）。
    # 性能护栏（T17 修复）：仅 QA 模式召回，编辑器 builder 流程不用「回忆偏好」；
    # 且查询 embedding 未缓存时跳过——避免每个交互一次 embedding API 往返（这是 agent 交互的隐性开销）。
    if query and not builder:
        try:
            from core import cache as embedding_cache
            from services.memory.memory_store import recall_memory

            if await embedding_cache.get_embedding(query) is None:
                logger.debug("L4 召回跳过：查询 embedding 未缓存（避免 API 往返）")
            else:
                memories = await recall_memory(user_id=user_id, query=query, top_k=3)
                if memories:
                    mem_parts = ["\n# 长期记忆（L4 语义记忆，来自历史会话）"]
                    for mem in memories:
                        mem_parts.append(f"- [{mem['score']:.2f}] {mem['text']}")
                    sections.append("\n".join(mem_parts))
        except Exception as e:
            logger.warning("L4 记忆召回失败（不影响主流程）: %s", e)

    # T12: 工具路由引导（事实性整文直读，模糊/跨模块才检索）
    sections.append(
        "\n# 工具使用指南\n"
        "- 事实性/定向问题（毕业院校、技能清单、某段经历细节）→ 优先 get_resume_content 读实时简历内容\n"
        "- 模糊/语义/跨模块问题 → 用 search_resume（单简历）或 search_assets（跨资产）检索\n"
        "- 需要深度推理且有依据的问题 → 用 answer_from_index（改写→检索→反思的深度回答）\n"
        "- JD 匹配 / 简历诊断 / STAR 改写 / 翻译 / 面试教练 → 用对应专用工具"
    )

    _total_ms = round((time.perf_counter() - _t0) * 1000)
    logger.info(
        "prompt_assembly_trace resume_query_ms=%d l3_ms=%d l2_ms=%d total_ms=%d",
        _resume_ms, _l3_ms, _l2_ms, _total_ms,
    )
    return "\n".join(sections)


# ═══════════════════════════════════════════════════════════════
# T15: L3 画像构建钩子 — ready 转换共享点
# ═══════════════════════════════════════════════════════════════

# L3 画像只需 summary + skills 两种（不调全量 4 种）
_L3_ANALYSIS_TYPES = ("summary", "skills")


async def build_l3_profile_background(resume_id: int, user_id: int) -> None:
    """后台构建 L3 紧凑画像（summary + skills）。

    在 resume 状态变为 ready 时触发，不阻塞热路径。
    只调 2 种分析类型，不调全量 4 种（experience/score 留给工具按需调）。

    错误不外抛——L3 画像缺失时 Agent 仍可工作（只是缺少长期画像注入）。

    双路径共享点：
    - 上传路径：process_resume_background → ready → 调本函数
    - Builder 路径：T24 保存并完成 → ready → 调本函数
    """
    async with AsyncSessionLocal() as db:
        for analysis_type in _L3_ANALYSIS_TYPES:
            try:
                await analyze_resume(
                    db=db,
                    user_id=user_id,
                    resume_id=resume_id,
                    analysis_type=analysis_type,
                )
                logger.info(
                    "L3 画像构建完成: resume_id=%d, type=%s",
                    resume_id, analysis_type,
                )
            except Exception as e:
                logger.warning(
                    "L3 画像构建失败（不影响主流程）: resume_id=%d, type=%s: %s",
                    resume_id, analysis_type, e,
                )
