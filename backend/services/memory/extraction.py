"""对话记忆提炼（T16, D8 写路径）。

对话结束后批处理：LLM 从对话提炼 1-3 条原子事实 → 与已有记忆语义去重 → 写入 L4。

设计要点：
- 复用 ``llm_generate``（重试/降级由 pipeline 保证）；失败返回空数组不阻塞主流程
- 去重用语义相似度（``recall_memory`` 高阈值），避免同一事实重复累积
- 调用方（RabbitMQ consumer / 对话结束钩子）负责调度，本模块只做提炼+写入
"""

import json
import logging
import re

from services.memory.memory_store import recall_memory, save_memory
from services.rag.pipeline import llm_generate

logger = logging.getLogger(__name__)

_MAX_FACTS = 3
# 去重相似度阈值：已有记忆与此事实相似度 >= 此值视为重复
_DEDUP_THRESHOLD = 0.85

_EXTRACT_SYSTEM = (
    "你是一个记忆提炼器。从用户与 AI 的对话中提炼值得长期记住的原子事实：\n"
    "1. 用户明确的偏好、目标、决定（例如『我想去字节做后端』）\n"
    "2. 用户个人背景（学校、城市、技能水平等）\n"
    "3. 对后续会话有复用价值的事实\n"
    "忽略：寒暄、一次性问题、与用户长期状态无关的内容。\n"
    "每条事实必须独立自包含（不依赖上下文即可理解）。最多提炼 3 条。\n"
    '严格按 JSON 字符串数组返回，不要包含其他文字：["事实1", "事实2"]'
)


def _parse_facts(raw: str, max_items: int = _MAX_FACTS) -> list[str]:
    """解析 LLM 返回的 JSON 数组；失败返回空列表（不阻塞）。"""
    if not raw:
        return []
    try:
        data = json.loads(raw.strip())
        if isinstance(data, list):
            facts = [str(f).strip() for f in data if str(f).strip()]
            return facts[:max_items]
    except (json.JSONDecodeError, ValueError):
        pass
    # 降级解析：抓取引号包裹的字符串
    facts = re.findall(r'"([^"]{4,})"', raw)
    return [f.strip() for f in facts][:max_items]


async def extract_and_save_memories(
    *,
    user_id: int,
    conversation_text: str,
    max_items: int = _MAX_FACTS,
) -> list[str]:
    """从对话提炼事实并写入 L4（语义去重），返回新写入的记忆 id 列表。

    任何失败都只记录、不抛出，保证后台批处理不因单次对话崩溃。
    """
    try:
        raw = await llm_generate(
            system=_EXTRACT_SYSTEM,
            user=conversation_text[:4000],
            temperature=0.2,
            max_tokens=300,
            user_id=user_id,
            fallback="[]",
        )
    except Exception as e:
        logger.warning("记忆提炼 LLM 失败: %s", e)
        return []

    facts = _parse_facts(raw, max_items)
    if not facts:
        return []

    saved: list[str] = []
    for fact in facts:
        try:
            # 语义去重：与已有记忆相似度过高 → 跳过（避免重复累积）
            existing = await recall_memory(
                user_id=user_id, query=fact, top_k=1, threshold=_DEDUP_THRESHOLD
            )
            if existing:
                continue
            mid = await save_memory(
                user_id=user_id, snippet=fact, memory_type="semantic"
            )
            saved.append(mid)
        except Exception as e:
            logger.warning("记忆写入失败: %s", e)

    logger.info("记忆提炼: user=%d 提炼 %d 条，新写入 %d 条", user_id, len(facts), len(saved))
    return saved
