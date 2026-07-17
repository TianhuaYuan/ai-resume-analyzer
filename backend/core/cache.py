"""Embedding 内存缓存：sha256(text)→vector，按 resume_id 追踪。"""

import asyncio
import hashlib

_cache: dict[str, list[float]] = {}
_resume_texts: dict[int, set[str]] = {}
_MAX_CACHE_SIZE = 5000
_lock = asyncio.Lock()


def embedding_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def get_embedding(text: str) -> list[float] | None:
    return _cache.get(embedding_key(text))


async def set_embedding(text: str, vector: list[float], resume_id: int | None = None) -> None:
    async with _lock:
        while len(_cache) >= _MAX_CACHE_SIZE:
            oldest_key = next(iter(_cache))
            del _cache[oldest_key]
        _cache[embedding_key(text)] = vector
        if resume_id is not None:
            _resume_texts.setdefault(resume_id, set()).add(text)

# 删除 resume（resumeid）的缓存未同（不够优雅）
async def clear_resume(resume_id: int) -> int:
    async with _lock:
        texts = _resume_texts.pop(resume_id, set())
        count = 0
        for text in texts:
            if _cache.pop(embedding_key(text), None) is not None:
                count += 1
        return count


async def clear() -> None:
    async with _lock:
        _cache.clear()
        _resume_texts.clear()


def stats() -> dict:
    return {
        "cache_entries": len(_cache),
        "tracked_resumes": len(_resume_texts),
    }
