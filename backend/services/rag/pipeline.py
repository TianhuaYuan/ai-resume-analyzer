"""端到端 RAG 编排 + LLM 生成。

阶段11 从 rag_service.py 拆出：把"分块/检索/重排"这些零件串成完整问答链路，
并承载与 LLM 交互的生成逻辑。用到 core.trace.StepTimer 做分步计时（契约不变）。
"""

import asyncio
import logging

from core.config import settings
from core.retry import with_retry
from core.trace import StepTimer
from services.rag.chunking import chunk_by_sections
from services.rag.clients import (
    _collection_name,
    get_chat_client,
    get_chroma_client,
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
) -> str:
    """调 Chat API 生成回答。

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
    return (response.choices[0].message.content or "").strip()


async def _llm_generate_stream(
    system: str,
    user: str,
    temperature: float = 0.1,
):
    """流式调 Chat API（模型由 settings.CHAT_MODEL 决定），逐 token yield delta text。

    最后 yield 一个 usage dict: {"prompt_tokens": int, "completion_tokens": int}
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
            yield {
                "type": "usage",
                "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(chunk.usage, "completion_tokens", 0),
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


async def ask_question_stream(resume_id: int, question: str):
    """RAG 全链路流式版：检索 → 流式生成，逐个 yield 事件 dict"""
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
        async for event in _llm_generate_stream(prompt["system"], prompt["user"]):
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
