"""端到端 RAG 编排 + LLM 生成。

阶段11 从 rag_service.py 拆出：把"分块/检索/重排"这些零件串成完整问答链路，
并承载与 LLM 交互的生成逻辑。用到 core.trace.StepTimer 做分步计时（契约不变）。
"""

import asyncio
import logging
from typing import Any

from core.config import settings
from core.rag_params import RagParams
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
    hybrid_search_p,
    reject_if_low_score,
    rerank,
    rerank_p,
)

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = "服务暂时不可用，请稍后重试。"


async def rewrite_query(question: str) -> str:
    """LLM 改写问题做指代消解，失败时返回原问题兜底"""
    system = "你是一个问题改写助手。"
    user = (
        "把用户的问题改写成完整、具体、适合向量检索的问题。保留所有关键实体。"
        "如果用户的问题包含'除了...以外'、'除...外还有哪些'等排除性表述，"
        "请将排除部分去掉，重新组织为只关注目标内容的查询。"
        "如果问题已经完整，直接返回原句。\n"
        f"用户问题：{question}\n"
        "改写后的问题："
    )
    rewritten = await with_retry(
        llm_generate,
        system,
        user,
        temperature=0.1,
        max_tokens=200,
        fallback=question,
    )
    return rewritten or question


async def llm_generate(
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
) -> str:
    """调 Chat API 生成回答（模型由 settings.CHAT_MODEL 决定），抽出来方便加不同的 temperature 和重试"""
    client = get_chat_client()
    kwargs = {
        "model": settings.CHAT_MODEL,
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
    """流式调 Chat API（模型由 settings.CHAT_MODEL 决定），逐 token yield delta text"""
    client = get_chat_client()
    stream = await client.chat.completions.create(
        model=settings.CHAT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue  # DeepSeek 流式 API 偶发空 choices 的信号 chunk
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def build_prompt(context_chunks: list[str], question: str) -> dict:
    """组装 System Prompt + 来源上下文"""
    context = "\n\n".join(f"[段落 {i + 1}]\n{text}" for i, text in enumerate(context_chunks))
    system = (
        "你是一个简历分析助手。请根据下面的简历内容回答问题。"
        "如果简历中没有直接相关信息，请明确说未提及，不要推测。"
        "如果简历中有部分相关内容，请基于已有信息给出最佳回答。"
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


async def ask_question(resume_id: int, question: str) -> tuple[str, list[dict]]:
    """RAG 全链路：检索 → Prompt → LLM 生成（同步）"""
    timer = StepTimer()

    rewritten, reranked = await _retrieve(resume_id, question, timer)
    if not reranked:
        timer.log()
        return ("抱歉，简历中未提及该信息。", [])

    prompt = build_prompt([c["text"] for c in reranked], rewritten)
    answer = await timer.run(
        "generate",
        with_retry(llm_generate, prompt["system"], prompt["user"], fallback=FALLBACK_MESSAGE),
    )

    timer.log()
    return answer, reranked


async def _retrieve_p(
    resume_id: int,
    question: str,
    p: RagParams,
    timer: StepTimer,
    collection_name: str | None = None,
    bm25_key: Any | None = None,
) -> tuple[str, list[dict]]:
    """参数化版检索链路。collection_name / bm25_key 用于参数化实验隔离（Model C）。"""
    rewritten = await timer.run("rewrite", rewrite_query(question))
    chunks = await timer.run(
        "hybrid",
        hybrid_search_p(
            resume_id, rewritten, p, collection_name=collection_name, bm25_key=bm25_key
        ),
    )
    if not chunks:
        return rewritten, []
    chunks = chunks[: p.rerank_input_top_k] if p.rerank_input_top_k > 0 else chunks
    if p.rerank_input_top_k == 0:
        # rerank_input_top_k=0 哨兵值：跳过 Rerank，直接使用 hybrid 结果
        # 用于验证 Rerank 是否真的提升质量（Phase 3 ablation）
        if reject_if_low_score(chunks, threshold=p.reject_threshold):
            return rewritten, []
        return rewritten, chunks
    reranked = await timer.run("rerank", rerank_p(rewritten, chunks, p))
    if reject_if_low_score(reranked, threshold=p.reject_threshold):
        return rewritten, []
    return rewritten, reranked


async def ask_question_p(
    resume_id: int,
    question: str,
    p: RagParams,
    collection_name: str | None = None,
    bm25_key: Any | None = None,
) -> tuple[str, list[dict], dict]:
    """参数化版 RAG 全链路，返回 (answer, sources, timings)。
    collection_name / bm25_key 为可选项，用于参数化实验隔离（Model C）；
    省略时行为不变（沿用 resume_{resume_id} 集合与默认 BM25 键）。
    """
    timer = StepTimer()

    rewritten, reranked = await _retrieve_p(
        resume_id,
        question,
        p,
        timer,
        collection_name=collection_name,
        bm25_key=bm25_key,
    )
    if not reranked:
        timer.log()
        return ("抱歉，简历中未提及该信息。", [], timer.steps)

    prompt = build_prompt([c["text"] for c in reranked], rewritten)
    answer = await timer.run(
        "generate",
        with_retry(
            llm_generate,
            prompt["system"],
            prompt["user"],
            temperature=p.generate_temperature,
            fallback=FALLBACK_MESSAGE,
        ),
    )

    timer.log()
    return answer, reranked, timer.steps


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
        async for token in _llm_generate_stream(prompt["system"], prompt["user"]):
            full += token
            yield {"type": "token", "content": token}
    except asyncio.CancelledError:
        raise  # 客户端断开连接，不吞异常
    except Exception:
        # 流式失败 → 降级为非流式重试一次
        logger.exception("Streaming failed, falling back to non-streaming")
        fallback = await with_retry(
            llm_generate,
            prompt["system"],
            prompt["user"],
            fallback=FALLBACK_MESSAGE,
        )
        full = fallback
        yield {"type": "token", "content": fallback}

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
