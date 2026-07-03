import logging
import os
import re
import shutil

import chromadb
import httpx
import jieba
from openai import AsyncOpenAI
from rank_bm25 import BM25Okapi

from core import cache as embedding_cache
from core.config import settings
from core.retry import FALLBACK_MESSAGE, with_retry
from core.trace import StepTimer

logger = logging.getLogger(__name__)


_chat_client: AsyncOpenAI | None = None
_embedding_client: AsyncOpenAI | None = None
_chroma_client = None
_bm25_indexes: dict[int, tuple[BM25Okapi, list[dict]]] = {}

SECTION_HEADERS = [
    # 教育
    "教育背景", "教育经历", "学历", "教育", "学习经历",
    # 工作 / 实习
    "工作经历", "工作经验", "实习经历", "实习经验", "工作", "实习",
    # 项目
    "项目经历", "项目经验", "项目展示", "项目",
    # 技能
    "专业技能", "技能", "技术栈", "技术能力", "个人技能", "掌握技能",
    # 评价 / 总结
    "自我评价", "个人总结", "自我介绍", "个人评价", "自我总结",
    # 其他
    "开源贡献", "开源", "证书", "获奖", "荣誉", "证书与奖项",
]
# 行首 + 可选的序号（一/1.） + 标题 + 冒号 + 换行
SECTION_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:(?:[一二三四五六七八九十]+|\d+)[、.）\)]?\s*)?("
    + "|".join(re.escape(h) for h in SECTION_HEADERS)
    + r")[\s:：]*\n",
    re.IGNORECASE,
)


def get_chat_client() -> AsyncOpenAI:
    global _chat_client
    if _chat_client is None:
        _chat_client = AsyncOpenAI(
            api_key=settings.CHAT_API_KEY,
            base_url=settings.CHAT_BASE_URL,
        )
    return _chat_client


def get_embedding_client() -> AsyncOpenAI:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = AsyncOpenAI(
            api_key=settings.EMBEDDING_API_KEY,
            base_url=settings.EMBEDDING_BASE_URL,
        )
    return _embedding_client


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    return _chroma_client


def _collection_name(resume_id: int) -> str:
    return f"resume_{resume_id}"


def _tokenize(text: str) -> list[str]:
    return list(jieba.cut_for_search(text))


def _split_by_sections(text: str) -> list[tuple[str, str]]:
    """按简历节段标题切分，无标题则整体返回"""
    if not SECTION_PATTERN.search(text):
        return [("正文", text)]

    parts = SECTION_PATTERN.split(text)
    sections = [("基本信息", parts[0].strip())]
    i = 1
    while i + 1 < len(parts):
        sections.append((parts[i].strip(), parts[i + 1].strip()))
        i += 2
    return sections


def _find_split(text: str, chunk_size: int, separators: list[str]) -> int:
    for sep in separators:
        pos = text.rfind(sep, int(chunk_size * 0.5), chunk_size)
        if pos > 0:
            return pos + len(sep)
    return chunk_size


def _recursive_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    separators = ["\n\n", "\n", "。", "，", " "]  # 按优先级切分
    result = []
    current = text
    while len(current) > chunk_size:
        split_pos = _find_split(current, chunk_size, separators)
        result.append(current[:split_pos])
        current = current[max(0, split_pos - overlap):]
    if current.strip():
        result.append(current)
    return result


def _make_chunk(text: str, section: str, index: int, offset: int) -> dict:
    return {
        "text": text,
        "section": section,
        "chunk_index": index,
        "start_char": offset,
        "end_char": offset + len(text),
    }


def chunk_by_sections(text: str, chunk_size: int = 80, overlap: int = 25) -> list[dict]:
    """结构感知分块：先按节段切，超长节段内部再递归细分"""
    sections = _split_by_sections(text)
    chunks = []
    idx = 0
    offset = 0
    for section, body in sections:
        body = body.strip()
        if not body:
            continue
        if len(body) <= chunk_size:
            chunks.append(_make_chunk(body, section, idx, offset))
            idx += 1
            offset += len(body)
        else:
            for sub in _recursive_split(body, chunk_size, overlap):
                chunks.append(_make_chunk(sub, section, idx, offset))
                idx += 1
                offset += len(sub)
    return chunks


def fixed_chunk(text: str, chunk_size: int, overlap: int = 50) -> list[dict]:
    """固定长度分块（对照实验用）"""
    chunks = []
    idx = 0
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(_make_chunk(text[start:end], "正文", idx, start))
        idx += 1
        start += chunk_size - overlap
    return chunks


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """批量调百炼 Embedding API，缓存命中跳过 API 调用"""
    vectors: list[list[float]] = []
    uncached_idx: list[int] = []
    uncached: list[str] = []

    for i, t in enumerate(texts):
        vec = embedding_cache.get_embedding(t)
        if vec is not None:
            vectors.append(vec)
        else:
            vectors.append([])  # placeholder，下面批量填
            uncached_idx.append(i)
            uncached.append(t)

    if uncached:
        client = get_embedding_client()
        for batch_start in range(0, len(uncached), 10):
            batch_texts = uncached[batch_start:batch_start + 10]
            batch_idx = uncached_idx[batch_start:batch_start + 10]
            response = await client.embeddings.create(
                model=settings.EMBEDDING_MODEL, input=batch_texts,
            )
            for j, item in enumerate(response.data):
                idx = batch_idx[j]
                vectors[idx] = item.embedding
                embedding_cache.set_embedding(batch_texts[j], item.embedding)

    return vectors


def _cleanup_orphan_segments() -> int:
    """清理 ChromaDB delete_collection 在 Windows 上留下的孤儿 HNSW 目录"""
    persist_dir = settings.CHROMA_PERSIST_DIR
    if not os.path.isdir(persist_dir):
        return 0

    # 从磁盘收集所有 UUID 格式的目录
    disk_dirs = set()
    for entry in os.listdir(persist_dir):
        full = os.path.join(persist_dir, entry)
        if os.path.isdir(full) and len(entry) == 36 and entry.count("-") == 4:
            disk_dirs.add(entry)

    if not disk_dirs:
        return 0

    # 从 SQLite 查活跃 segment ID
    try:
        client = get_chroma_client()
        # ChromaDB 不暴露 segments 列表，直接从 SQLite 读
        import sqlite3
        db_path = os.path.join(persist_dir, "chroma.sqlite3")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM segments")
        active = {row[0] for row in cur.fetchall()}
        conn.close()
    except Exception:
        return 0

    orphans = disk_dirs - active
    for d in orphans:
        shutil.rmtree(os.path.join(persist_dir, d), ignore_errors=True)
        logger.info("Removed orphan ChromaDB segment: %s", d)

    return len(orphans)


async def process_resume(resume_id: int, text: str) -> int:
    """清理旧向量 → 结构分块 → 向量化 → 存入 Chroma → 清空 BM25 缓存"""
    client = get_chroma_client()
    name = _collection_name(resume_id)
    # 同名 collection 存在才删，不存在跳过——避免每次新简历上传都打 warning
    existing = [c for c in client.list_collections() if c.name == name]
    if existing:
        client.delete_collection(name)
        _cleanup_orphan_segments()

    collection = client.get_or_create_collection(name=name)
    chunks = chunk_by_sections(text)
    if not chunks:
        return 0

    texts = [c["text"] for c in chunks]
    embeddings = await get_embeddings(texts)

    collection.add(
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

    _bm25_indexes.pop(resume_id, None)
    return len(chunks)


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
        _llm_generate, system, user, temperature=0.1, max_tokens=200, fallback=question,
    )
    return rewritten or question


async def hybrid_search(resume_id: int, question: str, top_k: int = 5) -> list[dict]:
    """稠密向量 + BM25 关键词 → RRF 融合 → 返回 top_k"""
    dense = await _vector_search(resume_id, question, top_k=20)
    sparse = await _keyword_search(resume_id, question, top_k=20)
    return _merge_results(dense, sparse, top_k)


async def _vector_search(resume_id: int, question: str, top_k: int) -> list[dict]:
    """稠密向量检索：问题转向量 → Chroma 余弦相似度查询，collection 不存在时返回空"""
    embedding = (await get_embeddings([question]))[0]
    name = _collection_name(resume_id)
    try:
        collection = get_chroma_client().get_collection(name)
    except Exception:
        logger.warning("Chroma collection %s not found, returning empty", name)
        return []
    results = collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        chunks.append({
            "text": results["documents"][0][i],
            "score": 1.0 - results["distances"][0][i],  # Chroma 默认 cosine distance，转相似度
            "chunk_index": meta["chunk_index"],
            "section": meta["section"],
            "source": "dense",
        })
    return chunks


def _load_bm25_index(resume_id: int) -> bool:
    """从 Chroma 读取文档构建 BM25 索引，返回是否加载成功"""
    name = _collection_name(resume_id)
    try:
        collection = get_chroma_client().get_collection(name)
    except Exception:
        logger.warning("Chroma collection %s not found, skip BM25 build", name)
        return False
    data = collection.get(include=["documents", "metadatas"])
    chunks = []
    for doc, meta in zip(data["documents"], data["metadatas"]):
        chunks.append({
            "text": doc,
            "chunk_index": meta["chunk_index"],
            "section": meta["section"],
        })
    if not chunks:
        return False
    tokenized = [_tokenize(c["text"]) for c in chunks]
    _bm25_indexes[resume_id] = (BM25Okapi(tokenized), chunks)
    return True


async def _keyword_search(resume_id: int, question: str, top_k: int) -> list[dict]:
    """BM25 关键词检索：懒加载索引 → 分词算分 → 返回 top_k，过滤零分结果"""
    if resume_id not in _bm25_indexes:
        if not _load_bm25_index(resume_id):
            return []

    index_data = _bm25_indexes.get(resume_id)
    if index_data is None:
        return []
    index, chunks = index_data
    scores = index.get_scores(_tokenize(question))
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [
        {
            "text": chunks[i]["text"],
            "score": float(scores[i]),
            "chunk_index": chunks[i]["chunk_index"],
            "section": chunks[i]["section"],
            "source": "sparse",
        }
        for i in top_indices if scores[i] > 0
    ]


def _merge_results(dense: list[dict], sparse: list[dict], top_k: int, k: int = 60) -> list[dict]:  # k: RRF 平滑常数，论文常用 60
    """RRF 融合：按排名而非分数合并两路结果，同一 chunk 两路都中则累加得分"""
    scores: dict[int, dict] = {}
    for rank, item in enumerate(dense):
        key = item["chunk_index"]
        scores[key] = {"item": item, "score": 1.0 / (k + rank + 1)}
    for rank, item in enumerate(sparse):
        key = item["chunk_index"]
        if key in scores:
            scores[key]["score"] += 1.0 / (k + rank + 1)
        else:
            scores[key] = {"item": item, "score": 1.0 / (k + rank + 1)}

    ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return [x["item"] for x in ranked[:top_k]]


async def _llm_generate(
    system: str, user: str, temperature: float = 0.3, max_tokens: int | None = None,
) -> str:
    """调 DeepSeek Chat 生成回答，抽出来方便加不同的 temperature 和重试"""
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


async def rerank(question: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """百炼 gte-rerank Cross-Encoder 精排：query+documents 送专有模型打分，取 top_k"""
    if len(chunks) <= top_k:
        for c in chunks:
            c["rerank_score"] = 1.0
        return chunks

    async def _call_api():
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                settings.RERANK_BASE_URL,
                json={
                    "model": settings.RERANK_MODEL,
                    "input": {
                        "query": question,
                        "documents": [c["text"][:400] for c in chunks],
                    },
                    "parameters": {"top_n": top_k},
                },
                headers={
                    "Authorization": f"Bearer {settings.RERANK_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

    try:
        data = await with_retry(_call_api, fallback=None)
        if data is None:
            raise RuntimeError("Rerank API 全部重试失败")
        results = data.get("output", {}).get("results", [])
    except Exception as e:
        logger.warning("Rerank API failed: %s, falling back to original order", e)
        for c in chunks:
            c["rerank_score"] = 0.5
        return chunks[:top_k]

    score_map: dict[int, float] = {r["index"]: r["relevance_score"] for r in results}
    for i, c in enumerate(chunks):
        c["rerank_score"] = score_map.get(i, 0.0)

    chunks.sort(key=lambda c: c.get("rerank_score", 0), reverse=True)
    return chunks[:top_k]


def reject_if_low_score(chunks: list[dict], threshold: float = 0.5) -> bool:
    """Rerank 后最高分低于阈值则拒答。阈值通过 20 个无答案问题测算"""
    if not chunks:
        return True
    max_score = max(c.get("rerank_score", 0) for c in chunks)
    return max_score < threshold


async def ask_question(resume_id: int, question: str) -> tuple[str, list[dict]]:
    """RAG 全链路：改写 → 混合检索(20) → Rerank(8) → 拒答判断 → Prompt → LLM → 返回"""
    timer = StepTimer()

    rewritten = await timer.run("rewrite", rewrite_query(question))
    chunks = await timer.run("hybrid", hybrid_search(resume_id, rewritten, top_k=20))

    if not chunks:
        return ("抱歉，简历中未提及该信息。", [])

    reranked = await timer.run("rerank", rerank(rewritten, chunks, top_k=8))

    if reject_if_low_score(reranked):
        timer.log()
        return ("抱歉，简历中未提及该信息。", [])

    prompt = build_prompt([c["text"] for c in reranked], rewritten)
    answer = await timer.run(
        "generate",
        with_retry(_llm_generate, prompt["system"], prompt["user"], fallback=FALLBACK_MESSAGE),
    )

    timer.log()
    return answer, reranked

async def _llm_generate_stream(
    system: str, user: str, temperature: float = 0.3,
):
    """流式调 DeepSeek Chat，逐 token yield delta text"""
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
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def ask_question_stream(resume_id: int, question: str):
    """RAG 全链路流式版：改写 → 混合检索 → Rerank → 流式生成，逐个 yield 事件 dict"""
    timer = StepTimer()

    rewritten = await timer.run("rewrite", rewrite_query(question))
    yield {"type": "status", "message": "检索中..."}

    chunks = await timer.run("hybrid", hybrid_search(resume_id, rewritten, top_k=20))

    if not chunks:
        timer.log()
        yield {"type": "done", "answer": "抱歉，简历中未提及该信息。", "sources": []}
        return

    reranked = await timer.run("rerank", rerank(rewritten, chunks, top_k=8))

    if reject_if_low_score(reranked):
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
    except Exception:
        # 流式失败 → 降级为非流式重试一次
        logger.warning("Streaming failed, falling back to non-streaming")
        fallback = await with_retry(
            _llm_generate, prompt["system"], prompt["user"], fallback=FALLBACK_MESSAGE,
        )
        full = fallback
        yield {"type": "token", "content": fallback}

    timer.log()
    yield {"type": "done", "answer": full, "sources": [c["text"] for c in reranked]}


def build_prompt(context_chunks: list[str], question: str) -> dict:
    """组装 System Prompt + 来源上下文"""
    context = "\n\n".join(
        f"[段落 {i + 1}]\n{text}" for i, text in enumerate(context_chunks)
    )
    system = (
        "你是一个简历分析助手。请根据下面的简历内容回答问题。"
        "如果简历中没有直接相关信息，请明确说未提及，不要推测。"
        "如果简历中有部分相关内容，请基于已有信息给出最佳回答。"
    )
    user = f"简历内容：\n{context}\n\n问题：{question}\n\n请给出简洁准确的回答。"
    return {"system": system, "user": user}


def clear_resume_vectors(resume_id: int) -> None:
    """删 Chroma collection + 清 BM25 内存缓存"""
    try:
        get_chroma_client().delete_collection(_collection_name(resume_id))
    except Exception:
        logger.warning("Failed to delete Chroma collection for resume %d", resume_id)
    _bm25_indexes.pop(resume_id, None)
