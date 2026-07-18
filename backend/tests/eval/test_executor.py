"""test_executor — FakeExecutor 确定性 + RealExecutor 集成（带 skip 守卫）。"""

from __future__ import annotations

import os

import pytest

from core.rag_params import RagParams
from eval.executor import (
    FakeExecutor,
    RealExecutor,
    bm25_key_for,
    namespace_collection_name,
)
from eval.protocol import ExecutorResult, TestSample


def _sample(resume_id: int = 1, question: str = "学历？") -> TestSample:
    return TestSample(
        id="q", resume_id=resume_id, category="factual", difficulty="easy",
        question=question, reference_answer="本科",
        keywords=["本科"], asker="hr", should_answer=True,
    )


async def test_fake_executor_deterministic():
    ex = FakeExecutor()
    entry = _sample(question="测试问题")
    res = await ex.execute(entry, RagParams())
    assert isinstance(res, ExecutorResult)
    assert res.answer == "[fake]测试问题"
    assert res.sources == [{"text": "fake-src", "section": ""}]
    # 多次调用一致
    res2 = await ex.execute(entry, RagParams())
    assert res2.answer == res.answer


def test_namespace_helpers():
    p = RagParams(chunk_size=800, overlap=50)
    assert namespace_collection_name(1, p) == "resume_1_cs800_ov50"
    assert bm25_key_for(1, p) == (1, 800, 50)


def _can_run_integration() -> bool:
    if os.getenv("EVAL_INTEGRATION") != "1":
        return False
    try:
        from services.rag.clients import get_chroma_client

        get_chroma_client().list_collections()
        return True
    except Exception:
        return False


@pytest.mark.integration
async def test_real_executor_integration():
    if not _can_run_integration():
        pytest.skip("需要 Chroma + Embedding/LLM 密钥（设置 EVAL_INTEGRATION=1）")

    resume_text = (
        "教育背景\n武汉理工大学 计算机科学与技术 本科 2015-2019\n"
        "工作经历\n某科技公司 后端工程师 2019-2023\n"
        "项目经历\n简历分析系统 负责检索模块\n"
        "技能\nPython FastAPI Chroma"
    )
    ex = RealExecutor(resume_texts={1: resume_text})
    params = RagParams(chunk_size=400, overlap=20)
    entry = _sample(resume_id=1, question="他什么学历？")

    result = await ex.execute(entry, params)
    assert isinstance(result, ExecutorResult)
    # 真实路径下要么拿到答案/拒答，要么异常降级（answer 为 str）
    assert isinstance(result.answer, str)

    # 清理：仅保留该参数的集合
    removed = ex.cleanup_stale_collections(1, keep=params)
    assert isinstance(removed, int)
    # 再清一次（keep=None 删全部匹配）
    ex.cleanup_stale_collections(1, keep=None)
