"""H2: BM25 索引字典无锁读取"""

import inspect
from services.rag.retrieval import _keyword_search


def test_h2_keyword_search_lock_should_cover_bm25_read():
    """_keyword_search 的 _bm25_lock 应覆盖 _bm25_indexes 的读取操作"""
    src = inspect.getsource(_keyword_search)
    lines = src.split("\n")

    # 找到锁的起始和结束位置
    lock_start = None
    lock_end = None
    in_lock = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if "async with _bm25_lock" in stripped:
            lock_start = i
            in_lock = True
        elif in_lock and stripped and not line.startswith(" ") and "async with" not in stripped:
            # 锁块结束（缩进恢复）
            lock_end = i
            break

    if lock_end is None:
        lock_end = len(lines)

    # 检查 _bm25_indexes 的读取是否在锁内
    bm25_read_in_lock = False
    for i in range(lock_start, lock_end):
        if "_bm25_indexes" in lines[i] and "get" in lines[i]:
            bm25_read_in_lock = True

    assert bm25_read_in_lock, (
        "_keyword_search 的 _bm25_lock 临界区应覆盖 _bm25_indexes.get() 的读取。"
        "当前锁只保护了 _load_bm25_index 调用（Line 385-388），"
        "Line 390 的 _bm25_indexes.get(resume_id) 在锁外执行，"
        "与 concurrent clear_resume_vectors 的 pop 存在数据竞争。"
    )
