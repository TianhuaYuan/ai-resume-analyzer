"""T14/T15: memory 装配 + L3 画像构建钩子。

三层记忆架构：
- L1 工作记忆：当前循环 messages，16k token 预算逐出（先丢最旧工具轮 → 再丢最旧对话轮）
- L2 情景记忆：qa_history 取最近 10 条
- L3 语义记忆：Redis 缓存的 summary+skills 紧凑画像（不调 get_full_analysis 四连发）

L3 画像构建钩子（T15）：
- ready 转换共享点后台构建（上传 + builder 双路径）
- 只调 summary + skills 两种分析类型（2 次 LLM，不调全量 4 种）
- 不阻塞热路径，错误不外抛

上下文压缩（ContextCompactor）：
- 自动检测 token 预算超限 → 结构化摘要替代手动逐出
- 保留最近 N 轮完整消息 + 旧消息的结构化摘要
- 支持增量更新：多次压缩时叠加摘要而非重复生成
- 降级路径：compact_l1_context 在无法压缩时回退到 manage_l1_context

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


def truncate_tool_result(text: str, max_chars: int | None = None) -> str:
    """截断工具结果到 ≤ max_chars 字符，超长部分用 ... 省略。

    max_chars=None 时用动态预算（P1-5 工具结果预算管理：随上下文窗口自适应，
    避免与 loop 层回灌截断口径不一致导致双重截断错乱）。
    """
    if not text:
        return ""
    if max_chars is None:
        # 懒导入避免循环依赖（loop 导入 memory）
        try:
            from services.react_agent.loop import _tool_result_budget

            max_chars = _tool_result_budget()
        except Exception:
            max_chars = MAX_TOOL_RESULT_CHARS
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
# 上下文压缩器：自动触发 + 结构化摘要 + 增量更新
# ═══════════════════════════════════════════════════════════════


class ContextCompactor:
    """结构化压缩器：当 token 预算超限时自动触发，生成摘要替代手动逐出。

    设计思路：
    - 与 manage_l1_context（手动逐出）互补：逐出丢弃信息，压缩保留信息摘要
    - 自动触发：should_compact 检测预算 → compact 执行压缩
    - 增量更新：多次压缩时 previous_summary 与新摘要合并，避免重复
    - 切割安全：find_cut_point 保证不在工具调用中间切割

    用法：
        compactor = ContextCompactor(context_window=16384)
        if compactor.should_compact(messages):
            messages = await compactor.compact(messages, llm_caller)
    """

    def __init__(self, context_window: int = 16384, reserve_tokens: int = 4096):
        """
        Args:
            context_window: 总 token 预算（对应 L1 工作记忆上限）
            reserve_tokens: 为 system prompt + 新回复预留的 token 数
        """
        self.context_window = context_window
        self.reserve_tokens = reserve_tokens
        self.previous_summary: str | None = None

    def estimate_tokens(self, messages: list[dict]) -> int:
        """估算消息列表的 token 数。

        复用模块级 count_message_tokens 的逻辑（中文 2 字/token，英文 4 字/token），
        但按消息粒度调用，方便 find_cut_point 逐条累加。
        """
        return count_message_tokens(messages)

    def should_compact(self, messages: list[dict]) -> bool:
        """判断是否需要压缩：当前 token 数超过可用预算。"""
        tokens = self.estimate_tokens(messages)
        budget = self.context_window - self.reserve_tokens
        return tokens > budget

    def find_cut_point(
        self, messages: list[dict], keep_recent_tokens: int = 4096
    ) -> int:
        """找到切割点：保留最近 keep_recent_tokens 的位置，保持轮次完整性。

        从末尾向前累加 token，直到超过 keep_recent_tokens。
        切割点会向前调整，确保：
        1. 不在 tool 角色消息中间切割（工具调用必须完整）
        2. 切割点在 user 消息之前（每个轮次从 user 开始）

        Returns:
            切割点索引：messages[:cut_point] 需要压缩，messages[cut_point:] 保留。
            返回 0 表示无法压缩（所有消息都需要保留）。
        """
        accumulated = 0
        cut_point = len(messages)

        for i in range(len(messages) - 1, -1, -1):
            msg_tokens = self.estimate_tokens([messages[i]])
            accumulated += msg_tokens
            if accumulated > keep_recent_tokens:
                # 找到粗略切割点，向前调整保证轮次完整性
                # 1. 跳过所有连续的 tool 消息（工具调用结果必须完整保留）
                while i > 0 and messages[i].get("role") == "tool":
                    i -= 1
                # 2. 确保切割点在 user 消息之前（轮次从 user 开始）
                while i > 0 and messages[i].get("role") != "user":
                    i -= 1
                # 3. 切割点设在该 user 消息之前，保留完整轮次
                return i

        return 0  # 所有消息都在预算内，无需切割

    async def compact(
        self, messages: list[dict], llm_caller=None
    ) -> list[dict]:
        """执行压缩：生成结构化摘要 + 保留最近消息。

        流程：
        1. 检查是否需要压缩
        2. 找到切割点（保留最近消息的起始位置）
        3. 对旧消息生成结构化摘要
        4. 构建压缩后的消息列表：[摘要 system 消息] + [最近消息]

        Args:
            messages: 当前消息列表
            llm_caller: LLM 调用函数（async callable），为 None 时使用模板摘要

        Returns:
            压缩后的消息列表
        """
        if not self.should_compact(messages):
            return messages

        # 找到切割点
        keep_recent_tokens = min(self.reserve_tokens, 4096)
        cut_point = self.find_cut_point(messages, keep_recent_tokens)
        if cut_point == 0:
            logger.debug("ContextCompactor: 无法压缩（所有消息都在预算内）")
            return messages

        # 分离：需要压缩的部分 + 需要保留的部分
        to_compress = messages[:cut_point]
        to_keep = messages[cut_point:]

        # 生成结构化摘要
        summary = await self._generate_summary(to_compress, llm_caller)

        # 如果有历史摘要，合并（增量更新）
        if self.previous_summary:
            summary = f"{self.previous_summary}\n\n---\n\n{summary}"
        self.previous_summary = summary

        # 构建压缩后的消息列表：摘要作为 system 消息 + 保留的最近消息
        # 注意：不移除原有的 system 消息（它们包含角色指令等重要信息）
        summary_block = (
            "# 上下文摘要（已压缩）\n"
            "以下是之前对话的结构化摘要，用于节省上下文窗口。\n\n"
            f"{summary}"
        )
        # System 指令（角色约束、工具安全规则）不可被摘要替换；将摘要追加到
        # 第一条 system，其余 system 保持原顺序，再接最近的非 system 消息。
        kept_systems = [m for m in messages if m.get("role") == "system"]
        if kept_systems:
            first_system = dict(kept_systems[0])
            first_system["content"] = f"{first_system.get('content', '')}\n\n{summary_block}"
            compressed_messages = [first_system, *[dict(m) for m in kept_systems[1:]]]
        else:
            compressed_messages = [{"role": "system", "content": summary_block}]
        compressed_messages.extend(m for m in to_keep if m.get("role") != "system")

        before_tokens = self.estimate_tokens(messages)
        after_tokens = self.estimate_tokens(compressed_messages)
        logger.info(
            "ContextCompactor: 压缩完成 %d -> %d tokens (节省 %d, %.1f%%)",
            before_tokens,
            after_tokens,
            before_tokens - after_tokens,
            (1 - after_tokens / max(before_tokens, 1)) * 100,
        )

        return compressed_messages

    async def _generate_summary(
        self, messages: list[dict], llm_caller=None
    ) -> str:
        """从旧消息中提取关键信息生成结构化摘要。

        如果提供 llm_caller，调用 LLM 生成高质量摘要；
        否则使用模板提取（零 LLM 开销的降级路径）。

        摘要结构：
        - 用户目标：最近的用户意图
        - 已完成任务：工具调用记录
        - 关键决策：assistant 的重要结论
        """
        user_goals: list[str] = []
        completed_tasks: list[str] = []
        key_decisions: list[str] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""

            if role == "user":
                # 保留用户目标（截断过长内容）
                goal = content[:300] if content else ""
                if goal:
                    user_goals.append(goal)

            elif role == "assistant":
                if msg.get("tool_calls"):
                    # 记录工具调用
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        name = func.get("name", "unknown")
                        completed_tasks.append(name)
                elif content:
                    # assistant 的文字回复中的关键结论
                    decision = content[:200]
                    if decision:
                        key_decisions.append(decision)

        # 如果有 LLM 调用函数，用 LLM 生成更高质量的摘要
        if llm_caller is not None:
            try:
                return await self._llm_summary(
                    messages, user_goals, completed_tasks, key_decisions, llm_caller
                )
            except Exception as e:
                logger.warning("ContextCompactor: LLM 摘要失败，降级为模板摘要: %s", e)

        # 模板降级：零 LLM 开销的结构化摘要
        return self._template_summary(user_goals, completed_tasks, key_decisions)

    async def _llm_summary(
        self,
        messages: list[dict],
        user_goals: list[str],
        completed_tasks: list[str],
        key_decisions: list[str],
        llm_caller,
    ) -> str:
        """调用 LLM 生成高质量结构化摘要。

        Args:
            llm_caller: async callable(prompt: str) -> str
        """
        # 构造摘要 prompt
        messages_text = "\n".join(
            f"[{m.get('role', '?')}]: {(m.get('content') or '')[:150]}"
            for m in messages[-20:]  # 最多传 20 条给 LLM 做摘要
        )
        prompt = (
            "请将以下对话历史压缩为结构化摘要，保留关键信息。\n"
            "输出格式（Markdown）：\n"
            "### 用户目标\n- 最近的用户意图（2-3 条）\n"
            "### 已完成\n- 工具调用和结果摘要（3-5 条）\n"
            "### 关键上下文\n- 重要结论和决策（2-3 条）\n\n"
            f"对话历史：\n{messages_text}"
        )

        summary = await llm_caller(prompt)
        return summary.strip() if summary else self._template_summary(
            user_goals, completed_tasks, key_decisions
        )

    def _template_summary(
        self,
        user_goals: list[str],
        completed_tasks: list[str],
        key_decisions: list[str],
    ) -> str:
        """模板降级摘要：零 LLM 开销，纯文本提取。"""
        parts = []

        if user_goals:
            parts.append("### 用户目标")
            # 只保留最近 3 个目标
            for goal in user_goals[-3:]:
                parts.append(f"- {goal}")
            parts.append("")

        if completed_tasks:
            parts.append("### 已完成任务")
            # 去重并保留最近 5 个
            seen: set[str] = set()
            unique_tasks: list[str] = []
            for t in completed_tasks:
                if t not in seen:
                    seen.add(t)
                    unique_tasks.append(t)
            for t in unique_tasks[-5:]:
                parts.append(f"- {t}")
            parts.append("")

        if key_decisions:
            parts.append("### 关键上下文")
            for d in key_decisions[-3:]:
                parts.append(f"- {d}")
            parts.append("")

        if not parts:
            return "（无可提取的关键信息）"

        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# L1 工作记忆：逐出管理（降级路径）
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
# L1 工作记忆：结构化压缩（升级路径）
# ═══════════════════════════════════════════════════════════════


async def compact_l1_context(
    messages: list[dict],
    llm_caller=None,
    max_tokens: int = DEFAULT_L1_BUDGET,
    compactor: ContextCompactor | None = None,
) -> list[dict]:
    """结构化压缩 L1 上下文（升级路径，优先于手动逐出）。

    与 manage_l1_context 的区别：
    - manage_l1_context：手动逐出，丢弃旧消息（信息不可恢复）
    - compact_l1_context：结构化压缩，旧消息生成摘要（信息以摘要形式保留）

    降级策略：
    - 有 llm_caller 且需要压缩 → ContextCompactor 压缩
    - 无需压缩 → 原样返回
    - 无法压缩（cut_point=0）或异常 → 回退到 manage_l1_context

    Args:
        messages: 当前消息列表
        llm_caller: LLM 调用函数（async callable），为 None 时用模板摘要
        max_tokens: token 预算上限

    Returns:
        压缩后的消息列表
    """
    compactor = compactor or ContextCompactor(context_window=max_tokens)

    if not compactor.should_compact(messages):
        return messages

    # 尝试结构化压缩
    try:
        compressed = await compactor.compact(messages, llm_caller)
        # 如果压缩后仍然超预算，用 manage_l1_context 做最终兜底
        if compactor.estimate_tokens(compressed) > max_tokens:
            logger.debug(
                "compact_l1_context: 压缩后仍超预算 (%d > %d)，降级为手动逐出",
                compactor.estimate_tokens(compressed),
                max_tokens,
            )
            return manage_l1_context(compressed, max_tokens)
        return compressed
    except Exception as e:
        logger.warning("compact_l1_context: 压缩异常，降级为手动逐出: %s", e)
        return manage_l1_context(messages, max_tokens)


# ═══════════════════════════════════════════════════════════════
# L2 情景记忆：qa_history 最近 10 条
# ═══════════════════════════════════════════════════════════════


async def get_l2_history(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
    limit: int = DEFAULT_L2_LIMIT,
    exclude_questions: set[str] | None = None,
) -> list[dict]:
    """从 qa_history 取最近 limit 条问答，按时间倒序。

    返回 [{"question": ..., "answer": ...}, ...]

    ``exclude_questions``（P2-9）：已作为完整 user/assistant 轮次注入的消息问题集合。
    同一批历史若既以 L2 摘要（200 字截断）注入 system prompt、又以完整轮次注入
    messages，会 token 重复携带。此处过滤掉已完整注入的问答，仅保留其余历史摘要。
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
    if exclude_questions:
        records = [r for r in records if r.question not in exclude_questions]
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
1. **交互式创建**：当用户请求创建简历时，必须采用一问一答的方式逐步收集信息，不要一次性问完所有问题。依次询问：
   - 目标岗位（必问）
   - 姓名（必问）
   - 教育背景（学校、专业、学历）
   - 工作/实习经历
   - 技能标签
   - 其他信息（选填）
   每次只问一个问题，等用户回答后再问下一个。收集完必要信息后，再调用 rewrite_resume 工具生成完整简历。

2. **工具优先**：写入/修改模块必须调用对应工具（generate_module / modify_module / rewrite_resume）提交，而非仅输出文字。

3. **简洁高效**：回答直击要点，工具调用后简要告知已写入哪个模块。

4. **归属隔离**：只能访问当前用户的简历。

5. **工具参数**：使用「当前简历」中给出的 resume_id，禁止猜测。

# 输出格式
- 交互式收集信息时，每次只问一个问题，用友好的语气引导用户。
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
    exclude_questions: set[str] | None = None,
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

    # L2 历史（P2-9：排除已作为完整轮次注入的问答，避免同一历史双重携带）
    l2_history = await get_l2_history(
        db, user_id, resume_id, exclude_questions=exclude_questions
    )
    _l2_ms = round((time.perf_counter() - _t2) * 1000)
    if l2_history:
        history_parts = ["\n# 历史问答（L2 情景记忆）"]
        for i, qa in enumerate(l2_history, 1):
            history_parts.append(f"{i}. Q: {qa['question']}")
            history_parts.append(f"   A: {qa['answer'][:200]}")
        sections.append("\n".join(history_parts))

    # L4 长期语义记忆（T15）：按当前问题语义召回，注入 system prompt（跨会话一致性）。
    # A3 实体增强：recall_with_entity_boost 在语义召回基础上，命中实体时把该实体有效事实
    # （resume_entity_facts，invalid_at IS NULL）RRF 融合进候选（借鉴 mem0 entity boost）。
    # 性能护栏（T17 修复）：仅 QA 模式召回，编辑器 builder 流程不用「回忆偏好」。
    # P2-3 修复：不再"查询 embedding 未缓存则跳过"——那会让进程重启后冷缓存下
    # 首轮交互永远拿不到长期记忆（功能被性能优化静默关闭）。recall_with_entity_boost
    # 内部 get_embeddings 本身有缓存，未缓存时补一次 API 往返（功能必需），失败静默
    # 降级为子串匹配，不阻塞主流程。
    if query and not builder:
        try:
            from services.memory.entity_link import recall_with_entity_boost

            memories = await recall_with_entity_boost(
                db=db, user_id=user_id, resume_id=resume_id, query=query, top_k=3
            )
            if memories:
                mem_parts = ["\n# 长期记忆（L4 语义记忆，来自历史会话）"]
                for mem in memories:
                    src = mem.get("metadata", {}).get("source")
                    tag = "实体" if src == "entity_fact" else "语义"
                    mem_parts.append(f"- [{tag}:{mem['score']:.2f}] {mem['text']}")
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
    """后台构建 L3 紧凑画像（summary + skills）+ A3 实体链接提取。

    在 resume 状态变为 ready 时触发，不阻塞热路径。
    只调 2 种分析类型，不调全量 4 种（experience/score 留给工具按需调）。

    错误不外抛——L3 画像缺失时 Agent 仍可工作（只是缺少长期画像注入）。

    A3 实体链接：画像文本（summary + skills）直接传给 extract_entities_from_profile
    （ADD-only 提取实体/事实 → 三表 + L4 记忆双向关联），失败不影响画像构建。

    双路径共享点：
    - 上传路径：process_resume_background → ready → 调本函数
    - Builder 路径：T24 保存并完成 → ready → 调本函数
    """
    async with AsyncSessionLocal() as db:
        summary_text = ""
        skills_text = ""
        for analysis_type in _L3_ANALYSIS_TYPES:
            try:
                result = await analyze_resume(
                    db=db,
                    user_id=user_id,
                    resume_id=resume_id,
                    analysis_type=analysis_type,
                )
                analysis = (result or {}).get("analysis") or ""
                if analysis_type == "summary":
                    summary_text = analysis
                else:
                    skills_text = analysis
                logger.info(
                    "L3 画像构建完成: resume_id=%d, type=%s",
                    resume_id, analysis_type,
                )
            except Exception as e:
                logger.warning(
                    "L3 画像构建失败（不影响主流程）: resume_id=%d, type=%s: %s",
                    resume_id, analysis_type, e,
                )

        # A3 实体链接：L3 画像 ADD-only 提取（失败不影响主流程）
        try:
            from services.memory.entity_link import extract_entities_from_profile

            await extract_entities_from_profile(
                db=db,
                user_id=user_id,
                resume_id=resume_id,
                summary=summary_text,
                skills=skills_text,
            )
        except Exception as e:
            logger.warning(
                "L3 实体提取失败（不影响主流程）: resume_id=%d: %s",
                resume_id, e,
            )
