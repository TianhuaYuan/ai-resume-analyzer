"""Embedding 内存缓存：sha256(text)→vector，按 resume_id 追踪。

使用 OrderedDict 实现 LRU 淘汰：每次访问/写入时 move_to_end，
淘汰时删除最久未使用的条目。

修复：
- _resume_texts 的 value 从原始 text 改为 embedding_key，方便 O(1) 反查
- 新增反向索引 _text_to_resume（embedding_key → resume_id），
  保证 LRU 淘汰 / clear_resume / text 重分配时能双向清理，避免内存泄漏
"""

import asyncio
import hashlib
from collections import OrderedDict

_cache: OrderedDict[str, list[float]] = OrderedDict()
# resume_id → set(embedding_key)：该 resume 关联的所有 embedding key
_resume_texts: dict[int, set[str]] = {}
# embedding_key → resume_id：反向索引，O(1) 找到 key 所属 resume
_text_to_resume: dict[str, int] = {}
_MAX_CACHE_SIZE = 5000
_lock = asyncio.Lock()


def embedding_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def get_embedding(text: str) -> list[float] | None:
    async with _lock:
        key = embedding_key(text)
        if key in _cache:
            _cache.move_to_end(key)  # LRU：标记为最近使用
            return _cache[key]
        return None


async def set_embedding(text: str, vector: list[float], resume_id: int | None = None) -> None:
    async with _lock:
        key = embedding_key(text)

        # 如果 key 之前关联过其他 resume，先从旧 resume 的 set 中移除
        old_resume_id = _text_to_resume.get(key)
        if old_resume_id is not None and old_resume_id != resume_id:
            _resume_texts.get(old_resume_id, set()).discard(key)

        if key in _cache:
            _cache.move_to_end(key)
        _cache[key] = vector

        # LRU 淘汰：超过上限时删除最久未使用的条目，同步清理反向索引
        while len(_cache) > _MAX_CACHE_SIZE:
            evicted_key, _ = _cache.popitem(last=False)
            evicted_resume_id = _text_to_resume.pop(evicted_key, None)
            if evicted_resume_id is not None:
                _resume_texts.get(evicted_resume_id, set()).discard(evicted_key)

        if resume_id is not None:
            _resume_texts.setdefault(resume_id, set()).add(key)
            _text_to_resume[key] = resume_id


async def clear_resume(resume_id: int) -> int:
    """删除指定 resume 关联的所有 embedding 缓存。返回实际从 _cache 删除的条目数。"""
    async with _lock:
        keys = _resume_texts.pop(resume_id, set())
        count = 0
        for key in keys:
            _text_to_resume.pop(key, None)
            if _cache.pop(key, None) is not None:
                count += 1
        return count


async def clear() -> None:
    async with _lock:
        _cache.clear()
        _resume_texts.clear()
        _text_to_resume.clear()


def stats() -> dict:
    return {
        "cache_entries": len(_cache),
        "tracked_resumes": len(_resume_texts),
    }
