"""内存缓存，用于 Embedding 结果去重——同一文本不重复调 API。

缓存按 SHA256(text) 作为 key，支持：
- 内容寻址：相同文本自动命中（跨简历共享）
- 按 resume_id 追踪：删除简历时只清该简历引用过的文本，不影响其他简历
"""
import asyncio
import hashlib

_cache: dict[str, list[float]] = {}
_resume_texts: dict[int, set[str]] = {}  # resume_id → 该简历用过的文本集合
_MAX_CACHE_SIZE = 5000  # 防止内存无限增长，超过后按 FIFO 淘汰
_lock = asyncio.Lock()


def embedding_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def get_embedding(text: str) -> list[float] | None:
    return _cache.get(embedding_key(text))


async def set_embedding(text: str, vector: list[float], resume_id: int | None = None) -> None:
    # FIFO 淘汰：超过上限时移除最早的条目
    async with _lock:
        while len(_cache) >= _MAX_CACHE_SIZE:
            oldest_key = next(iter(_cache))
            del _cache[oldest_key]
        _cache[embedding_key(text)] = vector
        if resume_id is not None:
            _resume_texts.setdefault(resume_id, set()).add(text)


async def clear_resume(resume_id: int) -> int:
    """删除指定简历的缓存条目，返回清除数量。跨简历复用的文本不会被删。"""
    async with _lock:
        texts = _resume_texts.pop(resume_id, set())
        count = 0
        for text in texts:
            if _cache.pop(embedding_key(text), None) is not None:
                count += 1
        return count


async def clear() -> None:
    """清空全部缓存（仅用于测试/重置场景）"""
    async with _lock:
        _cache.clear()
        _resume_texts.clear()


def stats() -> dict:
    return {
        "cache_entries": len(_cache),
        "tracked_resumes": len(_resume_texts),
    }
