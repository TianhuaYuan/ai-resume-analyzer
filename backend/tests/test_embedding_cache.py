"""P2-2: Embedding cache _resume_texts 无限增长修复测试。

核心问题：_cache LRU 淘汰时，_resume_texts 中的对应 text 没被清理，
导致 _resume_texts 无限增长（内存泄漏）。

修复：LRU 淘汰时同步清理 _resume_texts 和反向索引 _text_to_resume。
"""
import pytest

from core import cache as embedding_cache


@pytest.mark.asyncio
async def test_set_and_get_embedding():
    """基本 set/get 功能。"""
    await embedding_cache.clear()
    await embedding_cache.set_embedding("hello", [0.1, 0.2])
    vec = await embedding_cache.get_embedding("hello")
    assert vec == [0.1, 0.2]


@pytest.mark.asyncio
async def test_clear_resume_returns_evicted_count():
    """clear_resume 返回实际从 _cache 中删除的条目数。"""
    await embedding_cache.clear()
    await embedding_cache.set_embedding("A", [0.1], resume_id=1)
    await embedding_cache.set_embedding("B", [0.2], resume_id=1)
    cleared = await embedding_cache.clear_resume(1)
    assert cleared == 2


@pytest.mark.asyncio
async def test_lru_eviction_clears_resume_texts():
    """P2-2 核心：LRU 淘汰时同步清理 _resume_texts，避免内存泄漏。

    场景：
    1. 写入 1 条 embedding（resume_id=1, text="A"）
    2. 写入 _MAX_CACHE_SIZE 条其他 embedding，把 "A" 挤出 LRU
    3. 验证 _resume_texts[1] 不再包含 "A" 的 key（被淘汰时清理了）
    4. clear_resume(1) 应返回 0（因为 "A" 已被 LRU 淘汰）
    """
    await embedding_cache.clear()

    # 写入 1 条绑定 resume_id=1
    await embedding_cache.set_embedding("A", [0.1], resume_id=1)

    # 写入 _MAX_CACHE_SIZE 条其他 embedding，把 "A" 挤出 LRU
    for i in range(embedding_cache._MAX_CACHE_SIZE):
        await embedding_cache.set_embedding(f"filler-{i}", [float(i)])

    # "A" 应该已被 LRU 淘汰
    assert await embedding_cache.get_embedding("A") is None

    # _resume_texts[1] 应该不再包含 "A" 的 key（修复后）
    # 修复前：_resume_texts[1] 仍然包含 "A"，内存泄漏
    key_a = embedding_cache.embedding_key("A")
    resume_texts_1 = embedding_cache._resume_texts.get(1, set())
    assert key_a not in resume_texts_1, (
        f"LRU 淘汰后 _resume_texts[1] 仍包含被淘汰的 key，内存泄漏"
    )

    # clear_resume(1) 应返回 0（"A" 已被 LRU 淘汰，_cache 中没有）
    cleared = await embedding_cache.clear_resume(1)
    assert cleared == 0


@pytest.mark.asyncio
async def test_clear_resume_cleans_reverse_index():
    """clear_resume 后反向索引 _text_to_resume 也被清理。"""
    await embedding_cache.clear()
    await embedding_cache.set_embedding("A", [0.1], resume_id=1)
    await embedding_cache.set_embedding("B", [0.2], resume_id=1)

    key_a = embedding_cache.embedding_key("A")
    assert key_a in embedding_cache._text_to_resume

    await embedding_cache.clear_resume(1)

    assert key_a not in embedding_cache._text_to_resume


@pytest.mark.asyncio
async def test_text_reassignment_cleans_old_resume():
    """同一 text 关联新 resume_id 时，旧 resume_id 的 set 被清理。"""
    await embedding_cache.clear()
    await embedding_cache.set_embedding("shared", [0.1], resume_id=1)
    await embedding_cache.set_embedding("shared", [0.2], resume_id=2)

    key_shared = embedding_cache.embedding_key("shared")
    # 旧 resume_id=1 的 set 不应再包含 shared
    assert key_shared not in embedding_cache._resume_texts.get(1, set())
    # 新 resume_id=2 的 set 应包含 shared
    assert key_shared in embedding_cache._resume_texts.get(2, set())
    # 反向索引指向新 resume_id
    assert embedding_cache._text_to_resume[key_shared] == 2
