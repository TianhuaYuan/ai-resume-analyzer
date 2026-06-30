import logging
import re

import chromadb
import jieba
from openai import AsyncOpenAI
from rank_bm25 import BM25Okapi

from core.config import settings

logger = logging.getLogger(__name__)


_chat_client: AsyncOpenAI | None = None
_embedding_client: AsyncOpenAI | None = None
_chroma_client = None
_bm25_indexes: dict[int, tuple[BM25Okapi, list[dict]]] = {}

SECTION_HEADERS = [
    "教育背景", "教育经历", "工作经历", "实习经历", "项目经历", "项目经验",
    "专业技能", "技能", "个人技能", "技术栈", "自我评价", "个人总结",
]
SECTION_PATTERN = re.compile(
    r"(?:^|\n)\s*(" + "|".join(re.escape(h) for h in SECTION_HEADERS) + r")[\s:：]*\n",
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
    separators = ["\n\n", "\n", "。", "，", " "]
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


def chunk_by_sections(text: str, chunk_size: int = 500, overlap: int = 50) -> list[dict]:
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
    """批量调百炼 Embedding API"""
    client = get_embedding_client()
    response = await client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def process_resume(resume_id: int, text: str) -> int:
    """清理旧向量 → 结构分块 → 向量化 → 存入 Chroma → 清空 BM25 缓存"""
    client = get_chroma_client()
    name = _collection_name(resume_id)
    try:
        client.delete_collection(name)
    except Exception:
        logger.warning("Failed to delete Chroma collection %s before re-creating", name)

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
    prompt = (
        "把用户的问题改写成完整、具体、适合向量检索的问题。保留所有关键实体。"
        "如果问题已经完整，直接返回原句。\n"
        f"用户问题：{question}\n"
        "改写后的问题："
    )
    client = get_chat_client()
    response = await client.chat.completions.create(
        model=settings.CHAT_MODEL,
        messages=[
            {"role": "system", "content": "你是一个问题改写助手。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=200,
    )
    rewritten = (response.choices[0].message.content or "").strip()
    return rewritten or question


async def hybrid_search(resume_id: int, question: str, top_k: int = 5) -> list[dict]:
    """稠密向量 + BM25 关键词 → RRF 融合 → 返回 top_k"""
    dense = await _vector_search(resume_id, question, top_k=20)
    sparse = await _keyword_search(resume_id, question, top_k=20)
    return _merge_results(dense, sparse, top_k)


async def _vector_search(resume_id: int, question: str, top_k: int) -> list[dict]:
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
            "score": 1.0 - results["distances"][0][i],
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


def _merge_results(dense: list[dict], sparse: list[dict], top_k: int, k: int = 60) -> list[dict]:
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


async def ask_question(resume_id: int, question: str) -> tuple[str, list[dict]]:
    """RAG 全链路：改写 → 混合检索 → Prompt → LLM → 返回答案+来源"""
    rewritten = await rewrite_query(question)
    chunks = await hybrid_search(resume_id, rewritten, top_k=5)
    prompt = build_prompt([c["text"] for c in chunks], rewritten)

    client = get_chat_client()
    response = await client.chat.completions.create(
        model=settings.CHAT_MODEL,
        messages=[
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["user"]},
        ],
        temperature=0.3,
    )
    answer = (response.choices[0].message.content or "").strip()
    return answer, chunks


def build_prompt(context_chunks: list[str], question: str) -> dict:
    """组装 System Prompt + 来源上下文"""
    context = "\n\n".join(
        f"[段落 {i + 1}]\n{text}" for i, text in enumerate(context_chunks)
    )
    system = (
        "你是一个简历分析助手。请根据下面的简历内容回答问题。"
        "简历中未提及的信息请明确说未提及，不要推测。"
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
