"""M5: clear_resume_vectors 无锁操作 _bm25_indexes.pop()"""

import inspect
from services.rag.pipeline import clear_resume_vectors


def test_m5_clear_resume_vectors_should_acquire_bm25_lock():
    """clear_resume_vectors 在 pop _bm25_indexes 前应获取 _bm25_lock"""
    src = inspect.getsource(clear_resume_vectors)

    uses_lock = "_bm25_lock" in src

    assert uses_lock, (
        "clear_resume_vectors 在 pop _bm25_indexes 前应获取 _bm25_lock。"
        "当前 _keyword_search 在锁外读取 _bm25_indexes，"
        "clear_resume_vectors 在锁外修改 _bm25_indexes，"
        "可能导致并发时的 KeyError 或数据竞争。"
    )
