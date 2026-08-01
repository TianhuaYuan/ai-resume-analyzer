"""端到端 RAG 编排 + LLM 生成。

阶段11 从 rag_service.py 拆出：把"分块/检索/重排"这些零件串成完整问答链路，
并承载与 LLM 交互的生成逻辑。用到 core.trace.StepTimer 做分步计时（契约不变）。
"""

import asyncio
import logging
from dataclasses import dataclass, field

from core.config import settings
from core.retry import with_retry
from core.trace import StepTimer
from services.rag.usage import record_llm_usage
from services.rag.chunking import chunk_by_sections
from services.rag.clients import (
    _collection_name,
    get_chat_client,
    get_chroma_client,
    get_judge_client,
    reconnect_chroma,
    with_chroma,
)
from services.rag.retrieval import (
    _bm25_indexes,
    _bm25_lock,
    get_embeddings,
    hybrid_search,
    reject_if_low_score,
    rerank,
)

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = "服务暂时不可用，请稍后重试。"


# ═══════════════════════════════════════════════════════════
# T10: llm_generate_with_tools — ReAct Agent 的 LLM 调用基座
# 支持：tools（函数调用）/ thinking（推理链）/ include_usage / 流式 delta 解析
# ═══════════════════════════════════════════════════════════


@dataclass
class ToolCall:
    """LLM 返回的工具调用结构。"""
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class LLMToolResponse:
    """llm_generate_with_tools 非流式返回。"""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str | None = None
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})


def _select_client_and_model(model: str | None) -> tuple:
    """选择 LLM 客户端和模型名。model='judge' → JUDGE_MODEL + judge 客户端。"""
    if model == "judge":
        return get_judge_client(), settings.JUDGE_MODEL
    return get_chat_client(), model or settings.CHAT_MODEL


def _build_llm_kwargs(
    *,
    model_name: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int | None,
    tools: list[dict] | None,
    thinking_enabled: bool,
    thinking_effort: str,
    stream: bool = False,
) -> dict:
    """组装 LLM 请求 kwargs（非流式和流式共用）。"""
    kwargs: dict = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if tools:
        kwargs["tools"] = tools
    if thinking_enabled:
        kwargs["thinking"] = {"enabled": True, "effort": thinking_effort}
    if stream:
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
    return kwargs


def _parse_tool_calls_from_message(message) -> list[ToolCall]:
    """从非流式 response.choices[0].message 解析 tool_calls。"""
    tool_calls = []
    raw_tcs = getattr(message, "tool_calls", None)
    if raw_tcs:
        for tc in raw_tcs:
            func = getattr(tc, "function", None)
            tool_calls.append(ToolCall(
                id=getattr(tc, "id", "") or "",
                name=getattr(func, "name", "") or "" if func else "",
                arguments=getattr(func, "arguments", "") or "" if func else "",
            ))
    return tool_calls


async def llm_generate_with_tools(
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    model: str | None = None,
    user_id: int | None = None,
    thinking_enabled: bool = False,
    thinking_effort: str = "high",
) -> LLMToolResponse:
    """带 tools + thinking 的 LLM 调用（非流式）。

    Args:
        messages: OpenAI 格式消息列表
        tools: OpenAI function calling 工具定义
        temperature: 温度参数
        max_tokens: 最大生成 token 数
        model: 模型选择，'judge' 使用 JUDGE_MODEL
        user_id: 传入时记录 LLM usage
        thinking_enabled: 是否启用 thinking/reasoning
        thinking_effort: thinking 努力程度 (low/medium/high)

    Returns:
        LLMToolResponse: content + tool_calls + reasoning_content + usage
    """
    client, model_name = _select_client_and_model(model)
    kwargs = _build_llm_kwargs(
        model_name=model_name,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        thinking_enabled=thinking_enabled,
        thinking_effort=thinking_effort,
    )
    response = await client.chat.completions.create(**kwargs)

    # usage 解析 + 记账
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    if hasattr(response, "usage") and response.usage:
        pt = getattr(response.usage, "prompt_tokens", 0) or 0
        ct = getattr(response.usage, "completion_tokens", 0) or 0
        usage["prompt_tokens"] = pt
        usage["completion_tokens"] = ct
        if user_id is not None:
            await record_llm_usage(user_id, pt, ct)

    message = response.choices[0].message
    content = message.content or "" if hasattr(message, "content") else ""
    reasoning_content = getattr(message, "reasoning_content", None)
    tool_calls = _parse_tool_calls_from_message(message)

    return LLMToolResponse(
        content=content,
        tool_calls=tool_calls,
        reasoning_content=reasoning_content,
        usage=usage,
    )


async def llm_generate_with_tools_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    model: str | None = None,
    user_id: int | None = None,
    thinking_enabled: bool = False,
    thinking_effort: str = "high",
):
    """带 tools + thinking 的流式 LLM 调用。

    Yields events:
        {"type": "token", "content": str}
        {"type": "reasoning", "content": str}
        {"type": "tool_call_delta", "index": int}
        {"type": "usage", "prompt_tokens": int, "completion_tokens": int}
        {"type": "done", "content": str, "tool_calls": list[ToolCall]}
    """
    client, model_name = _select_client_and_model(model)
    kwargs = _build_llm_kwargs(
        model_name=model_name,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        thinking_enabled=thinking_enabled,
        thinking_effort=thinking_effort,
        stream=True,
    )
    stream = await client.chat.completions.create(**kwargs)

    content_parts: list[str] = []
    # tool_call 累积: {index: {"id": str, "name": str, "arguments": str}}
    tool_call_accum: dict[int, dict] = {}

    async for chunk in stream:
        # usage 在最后一个 chunk（choices 为空，只有 usage）
        if hasattr(chunk, "usage") and chunk.usage:
            pt = getattr(chunk.usage, "prompt_tokens", 0) or 0
            ct = getattr(chunk.usage, "completion_tokens", 0) or 0
            if user_id is not None:
                await record_llm_usage(user_id, pt, ct)
            yield {"type": "usage", "prompt_tokens": pt, "completion_tokens": ct}
            continue

        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta

        # reasoning_content（thinking 分块）
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            yield {"type": "reasoning", "content": reasoning}

        # content（正常 token）
        if delta.content:
            content_parts.append(delta.content)
            yield {"type": "token", "content": delta.content}

        # tool_calls delta 累积
        raw_tcs = getattr(delta, "tool_calls", None)
        if raw_tcs:
            for tc_delta in raw_tcs:
                idx = getattr(tc_delta, "index", 0)
                if idx not in tool_call_accum:
                    tool_call_accum[idx] = {"id": "", "name": "", "arguments": ""}

                tc_id = getattr(tc_delta, "id", None)
                if tc_id:
                    tool_call_accum[idx]["id"] = tc_id

                func = getattr(tc_delta, "function", None)
                if func:
                    name = getattr(func, "name", None)
                    if name and isinstance(name, str):
                        tool_call_accum[idx]["name"] = name
                    args = getattr(func, "arguments", None)
                    if args and isinstance(args, str):
                        tool_call_accum[idx]["arguments"] += args

                yield {"type": "tool_call_delta", "index": idx}

    # 聚合最终 tool_calls
    final_tool_calls = [
        ToolCall(
            id=tool_call_accum[idx]["id"],
            name=tool_call_accum[idx]["name"],
            arguments=tool_call_accum[idx]["arguments"],
        )
        for idx in sorted(tool_call_accum.keys())
    ]

    yield {
        "type": "done",
        "content": "".join(content_parts),
        "tool_calls": final_tool_calls,
    }


async def rewrite_query(question: str, model: str | None = None) -> str:
    """LLM 改写问题做指代消解，失败时返回原问题兜底（轻量重试 — flash 模型单次 ~0.3s）"""
    system = "你是一个问题改写助手。"
    user = (
        "把用户的问题改写成完整、具体、适合向量检索的问题。保留所有关键实体。"
        "如果用户的问题包含'除了...以外'、'除...外还有哪些'等排除性表述，"
        "请将排除部分去掉，重新组织为只关注目标内容的查询。"
        "如果问题已经完整，直接返回原句。\n"
        f"用户问题：{question}\n"
        "改写后的问题："
    )
    result = await with_retry(
        llm_generate,
        system,
        user,
        temperature=0.1,
        max_tokens=200,
        model=model,
        fallback=question,
    )
    return result or question


async def llm_generate(
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    model: str | None = None,
    user_id: int | None = None,
) -> str:
    """调 Chat API 生成回答。

    Args:
        user_id: 传入时成功后记录 LLM usage。

    Returns:
        回答文本（字符串）
    """
    client = get_chat_client()
    kwargs = {
        "model": model or settings.CHAT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    response = await client.chat.completions.create(**kwargs)

    # T3: 统一记账（只记成功）
    if user_id is not None and hasattr(response, "usage") and response.usage:
        pt = getattr(response.usage, "prompt_tokens", 0) or 0
        ct = getattr(response.usage, "completion_tokens", 0) or 0
        await record_llm_usage(user_id, pt, ct)

    return (response.choices[0].message.content or "").strip()


async def _llm_generate_stream(
    system: str,
    user: str,
    temperature: float = 0.1,
    user_id: int | None = None,
):
    """流式调 Chat API（模型由 settings.CHAT_MODEL 决定），逐 token yield delta text。

    最后 yield 一个 usage dict: {"prompt_tokens": int, "completion_tokens": int}

    Args:
        user_id: 传入时，收到 usage 后记录 LLM usage。
    """
    client = get_chat_client()
    stream = await client.chat.completions.create(
        model=settings.CHAT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        stream=True,
        stream_options={"include_usage": True},  # 请求返回 token 使用量
    )
    async for chunk in stream:
        # 检查是否有 usage 信息（在最后一个 chunk）
        if hasattr(chunk, "usage") and chunk.usage:
            pt = getattr(chunk.usage, "prompt_tokens", 0) or 0
            ct = getattr(chunk.usage, "completion_tokens", 0) or 0
            # T3: 流式 usage 记账
            if user_id is not None:
                await record_llm_usage(user_id, pt, ct)
            yield {
                "type": "usage",
                "prompt_tokens": pt,
                "completion_tokens": ct,
            }
            continue

        if not chunk.choices:
            continue  # DeepSeek 流式 API 偶发空 choices 的信号 chunk
        delta = chunk.choices[0].delta.content
        if delta:
            yield {"type": "token", "content": delta}


def build_prompt(context_chunks: list[str], question: str) -> dict:
    """组装 System Prompt + 来源上下文"""
    context = "\n\n".join(f"[段落 {i + 1}]\n{text}" for i, text in enumerate(context_chunks))
    system = (
        "你是一个简历分析助手。请根据下面的简历内容回答问题。"
        "如果简历中有直接相关信息，请基于这些信息给出最佳回答。"
        "如果简历中没有直接相关信息，可以进行合理推断（例如从缺失的技能/经历推断短板），"
        "但需明确区分哪些是简历直接提到的、哪些是你的推断。切忌编造事实。"
    )
    user = f"简历内容：\n{context}\n\n问题：{question}\n\n请给出简洁准确的回答。"
    return {"system": system, "user": user}


async def process_resume(resume_id: int, text: str) -> int:
    """清理旧向量 → 结构分块 → 向量化 → 存入 Chroma → 清空 BM25 缓存"""
    client = get_chroma_client()
    name = _collection_name(resume_id)

    def _sync_chroma_ops():
        try:
            client.delete_collection(name)
        except Exception:
            pass  # collection 不存在，忽略
        coll = client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
        coll.add(
            ids=[str(c["chunk_index"]) for c in chunks],
            documents=texts,
            embeddings=embeddings,
            metadatas=[
                {
                    "resume_id": resume_id,
                    "chunk_index": c["chunk_index"],
                    "section": c["section"],
                    "start_char": c["start_char"],
                    "end_char": c["end_char"],
                }
                for c in chunks
            ],
        )

    chunks = chunk_by_sections(text)
    if not chunks:
        return 0

    texts = [c["text"] for c in chunks]
    embeddings = await get_embeddings(texts, resume_id)

    # Bug 3 修复：Chroma 操作通过全局 with_chroma 锁串行化
    await with_chroma(_sync_chroma_ops)

    _bm25_indexes.pop(resume_id, None)
    return len(chunks)


async def _retrieve(resume_id: int, question: str, timer: StepTimer) -> tuple[str, list[dict]]:
    """检索链路：改写 → 混合检索(20) → Rerank(5) → 拒答判断。
    返回 (rewritten_question, reranked_chunks)。检索失败时 reranked_chunks 为空。"""
    rewritten = await timer.run("rewrite", rewrite_query(question))
    chunks = await timer.run("hybrid", hybrid_search(resume_id, rewritten, top_k=20))
    if not chunks:
        return rewritten, []
    reranked = await timer.run("rerank", rerank(rewritten, chunks, top_k=5))
    if reject_if_low_score(reranked):
        return rewritten, []
    return rewritten, reranked


async def ask_question_stream(resume_id: int, question: str, user_id: int | None = None):
    """RAG 全链路流式版：检索 → 流式生成，逐个 yield 事件 dict

    Args:
        user_id: 传入时，LLM usage 会记录到该用户名下。
    """
    timer = StepTimer()

    yield {"type": "status", "message": "检索中..."}
    rewritten, reranked = await _retrieve(resume_id, question, timer)

    if not reranked:
        timer.log()
        yield {"type": "done", "answer": "抱歉，简历中未提及该信息。", "sources": []}
        return

    prompt = build_prompt([c["text"] for c in reranked], rewritten)
    yield {"type": "status", "message": "生成中..."}

    full = ""
    try:
        async for event in _llm_generate_stream(prompt["system"], prompt["user"], user_id=user_id):
            if event["type"] == "usage":
                yield event  # 转发 usage 事件给调用方记录 token
                continue
            content = event.get("content", "")
            full += content
            yield {"type": "token", "content": content}
    except asyncio.CancelledError:
        raise  # 客户端断开连接，不吞异常
    except Exception:
        # 流式失败 → 降级为非流式重试一次
        logger.exception("Streaming failed, falling back to non-streaming")
        fallback_resp, _ = await with_retry(
            llm_generate,
            prompt["system"],
            prompt["user"],
            fallback=(FALLBACK_MESSAGE, {}),
        )
        full = fallback_resp
        # 通知客户端丢弃已收到的部分 token，用降级答案替换
        yield {"type": "reset"}
        yield {"type": "token", "content": fallback_resp}

    timer.log()
    yield {
        "type": "done",
        "answer": full,
        "sources": [
            {"chunk_index": c["chunk_index"], "text": c["text"], "section": c["section"]}
            for c in reranked
        ],
    }


async def clear_resume_vectors(resume_id: int) -> None:
    """删 Chroma collection + 清 BM25 内存缓存"""
    try:
        # Bug 3 修复：Chroma 删除操作也走全局锁
        await with_chroma(get_chroma_client().delete_collection, _collection_name(resume_id))
    except Exception:
        logger.warning("Failed to delete Chroma collection for resume %d, reconnecting", resume_id)
        reconnect_chroma()  # N2：ChromaDB 重连
    # M5 修复：pop _bm25_indexes 必须在 _bm25_lock 临界区内，避免与 _keyword_search 竞争
    async with _bm25_lock:
        _bm25_indexes.pop(resume_id, None)
