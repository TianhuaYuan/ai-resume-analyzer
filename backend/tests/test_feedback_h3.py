"""H3: rerank 函数原地修改输入 chunks"""
import inspect
import pytest
from services.rag_service import rerank


def test_h3_rerank_should_not_mutate_input_chunks():
    """rerank 不应原地修改输入 chunks，应返回新列表或深拷贝后再修改"""
    src = inspect.getsource(rerank)

    # 检查是否有原地修改的代码模式
    mutates_inplace = "c[\"rerank_score\"]" in src

    assert not mutates_inplace, (
        "rerank 不应原地修改输入 chunks（c['rerank_score'] = ...）。"
        "当前 Line 477-478 和 482-483 直接修改了传入的 dict 引用，"
        "调用方如果后续使用原始 chunks 列表，会看到被污染的数据。"
        "应改为深拷贝或返回新列表。"
    )


def test_h3_rerank_should_not_mutate_sort_inplace():
    """rerank 不应原地排序输入 chunks"""
    src = inspect.getsource(rerank)

    # 检查是否有原地排序
    inplace_sort = "chunks.sort" in src

    assert not inplace_sort, (
        "rerank 不应原地排序输入 chunks（chunks.sort(...)）。"
        "当前 Line 485 直接对传入的 chunks 列表排序，"
        "改变了调用方的数据顺序。应改为 sorted(chunks, ...) 返回新列表。"
    )