"""T35: L1 基准测试 + L2 并发压测（全 mock，无真实 LLM 调用）。

L1 基准（单请求延迟阈值）：
- 检索延迟 < 500ms（mock embedding + Chroma）
- Agent 循环延迟 < 3s（mock LLM，1轮收敛）
- 记忆装配延迟 < 200ms

L2 并发压测：
- 50 并发 Agent 请求，P99 < 5s，全 mock（无真实 LLM model calls）

所有 LLM 调用均被 mock，不产生真实 API 请求。
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from models.qa_history import QAHistory
from models.resume import Resume
from services.rag.pipeline import LLMToolResponse
from tests.conftest import AsyncSessionTest


# ── 辅助函数 ──────────────────────────────────────────────────


def _make_llm_response(content: str = "测试答案", tool_calls=None) -> LLMToolResponse:
    """构造 LLMToolResponse（mock LLM 返回值）。"""
    return LLMToolResponse(
        content=content,
        tool_calls=tool_calls or [],
        reasoning_content=None,
        usage={"prompt_tokens": 100, "completion_tokens": 50},
    )


def _make_stream_response(content: str = "测试答案", tool_calls=None):
    """构造模拟 llm_generate_with_tools_stream 的 async generator。

    中间轮改流式后，react_loop 通过 _stream_middle_round 消费该流，
    content 需通过 token 事件累积，done 只携带聚合后的 tool_calls。
    async generator 不可复用，多轮/并发需每次生成独立实例。
    """
    async def _gen():
        if content:
            yield {"type": "token", "content": content}
        yield {"type": "done", "content": content, "tool_calls": tool_calls or []}
    return _gen()


async def _create_resume(db_session, user_id: int, status: str = "ready") -> Resume:
    """在测试 DB 中创建一份简历并返回。"""
    resume = Resume(
        user_id=user_id,
        filename="test_resume.pdf",
        file_path="/tmp/test_resume.pdf",
        parsed_text="张三\nPython 工程师\n3年经验\n本科毕业\n熟练 FastAPI",
        chunk_count=3,
        status=status,
        source="upload",
    )
    db_session.add(resume)
    await db_session.commit()
    await db_session.refresh(resume)
    return resume


async def _create_qa_history(db_session, user_id: int, resume_id: int, count: int = 5) -> None:
    """创建若干 QA 历史记录（L2 情景记忆数据）。"""
    for i in range(count):
        record = QAHistory(
            user_id=user_id,
            resume_id=resume_id,
            question=f"测试问题 {i}",
            answer=f"测试答案 {i}，包含一些详细内容用于记忆装配测试。",
            sources=[],
            status="complete",
        )
        db_session.add(record)
    await db_session.commit()


# ═══════════════════════════════════════════════════════════════
# L1: 检索延迟基准
# ═══════════════════════════════════════════════════════════════


class TestL1RetrievalBenchmark:
    """L1: 检索延迟基准（< 500ms）。

    测试 hybrid_search 的端到端延迟：向量检索 + BM25 关键词检索 + RRF 融合。
    所有外部依赖（Embedding API、ChromaDB）均被 mock，只测量检索编排逻辑。
    """

    @pytest.mark.asyncio
    async def test_retrieval_latency(self, db_session, registered_user):
        """单次检索延迟 < 500ms（mock embedding + Chroma）。"""
        from services.rag.retrieval import _bm25_indexes, hybrid_search

        user_id = registered_user["id"]
        resume = await _create_resume(db_session, user_id)

        # 清理 BM25 缓存，确保测试隔离
        _bm25_indexes.pop(resume.id, None)

        # ── 构造 Mock Chroma 数据 ──────────────────────────────
        mock_documents = [
            "张三，Python 工程师，3年开发经验",
            "熟练使用 FastAPI、SQLAlchemy、Redis",
            "本科毕业，计算机科学与技术专业",
        ]
        mock_metadatas = [
            {"chunk_index": 0, "section": "title"},
            {"chunk_index": 1, "section": "skills"},
            {"chunk_index": 2, "section": "education"},
        ]

        mock_collection = MagicMock()
        # collection.get() 用于 BM25 索引构建
        mock_collection.get.return_value = {
            "documents": mock_documents,
            "metadatas": mock_metadatas,
        }
        # collection.query() 用于向量检索
        mock_collection.query.return_value = {
            "ids": [["0", "1", "2"]],
            "documents": [mock_documents],
            "metadatas": [mock_metadatas],
            "distances": [[0.1, 0.3, 0.5]],
        }
        mock_chroma_client = MagicMock()
        mock_chroma_client.get_collection.return_value = mock_collection

        # with_chroma 原本通过 asyncio.to_thread + 全局锁串行化执行，
        # 测试中直接同步调用 mock 函数即可（mock 数据无并发风险）
        async def mock_with_chroma(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch(
            "services.rag.retrieval.get_chroma_client",
            return_value=mock_chroma_client,
        ), patch(
            "services.rag.retrieval.get_embeddings",
            new_callable=AsyncMock,
            return_value=[[0.1, 0.2, 0.3, 0.4, 0.5]],
        ), patch(
            "services.rag.retrieval.with_chroma",
            side_effect=mock_with_chroma,
        ):
            start = time.perf_counter()
            results = await hybrid_search(resume.id, "Python 经验", top_k=5)
            elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(results) > 0, "检索应返回结果"
        # SQLite in-memory + mock Chroma/embedding，500ms 阈值有充足余量
        # 生产环境 MySQL + 真实 Chroma 预计更快（连接池复用 + HNSW 优化）
        assert elapsed_ms < 500, (
            f"检索延迟 {elapsed_ms:.1f}ms 超过 500ms 阈值"
        )


# ═══════════════════════════════════════════════════════════════
# L1: Agent 循环延迟基准
# ═══════════════════════════════════════════════════════════════


class TestL1LoopBenchmark:
    """L1: Agent 循环延迟基准（< 3s）。

    测试 react_loop 端到端延迟：配额检查 → system prompt 装配 → LLM 调用 → 返回。
    LLM 被 mock 为 1 轮收敛（直接回答，不调工具），测量循环编排开销。
    """

    @pytest.mark.asyncio
    async def test_loop_latency(self, db_session, registered_user):
        """单次 ReAct 循环 < 3s（mock LLM，1轮收敛）。"""
        import services.react_agent.loop as loop_module
        from services.react_agent.loop import react_loop

        user_id = registered_user["id"]
        resume = await _create_resume(db_session, user_id)

        # 重置 Semaphore（避免绑定到前一个测试的 event loop）
        loop_module._agent_semaphore = None

        # 1 轮收敛：中间轮流式直接返回答案，不调任何工具（最终轮不触发）
        stream_mock = MagicMock(side_effect=[_make_stream_response(content="测试答案")])

        with patch(
            "services.react_agent.loop.assemble_system_prompt",
            new_callable=AsyncMock,
        ) as mock_sys, patch(
            "services.react_agent.loop.check_quota",
            new_callable=AsyncMock,
        ) as mock_quota, patch(
            "services.react_agent.loop.llm_generate_with_tools",
            new_callable=AsyncMock,
        ) as mock_llm, patch(
            "services.react_agent.loop.llm_generate_with_tools_stream",
            stream_mock,
        ), patch(
            "services.react_agent.loop.get_agent_schemas",
            return_value=[],
        ), patch(
            "services.react_agent.loop.manage_l1_context",
        ) as mock_l1:

            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_llm_response(content="不应到达")

            start = time.perf_counter()
            result = await react_loop(
                db=db_session,
                user_id=user_id,
                resume_id=resume.id,
                question="测试问题",
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

        assert result.answer == "测试答案"
        assert mock_llm.call_count == 0, "1 轮收敛应走中间轮流式，最终轮不调用"
        assert stream_mock.call_count == 1
        # mock LLM 即时返回，3s 阈值有充足余量
        assert elapsed_ms < 3000, (
            f"循环延迟 {elapsed_ms:.1f}ms 超过 3s 阈值"
        )


# ═══════════════════════════════════════════════════════════════
# L1: 记忆装配延迟基准
# ═══════════════════════════════════════════════════════════════


class TestL1MemoryBenchmark:
    """L1: 记忆装配延迟基准（< 200ms）。

    测试 assemble_system_prompt 端到端延迟：L3 画像读取 + L2 历史查询 + prompt 拼接。
    L3 画像（Redis 缓存）被 mock，L2 历史从测试 DB 读取。
    """

    @pytest.mark.asyncio
    async def test_memory_assembly_latency(self, db_session, registered_user):
        """记忆装配 < 200ms。"""
        from services.react_agent.memory import assemble_system_prompt

        user_id = registered_user["id"]
        resume = await _create_resume(db_session, user_id)
        # 创建 L2 历史记录（5 条）
        await _create_qa_history(db_session, user_id, resume.id, count=5)

        # Mock L3 画像（Redis 缓存命中）
        mock_l3_profile = {
            "summary": "Python 工程师，3年经验，擅长 FastAPI",
            "skills": ["Python", "FastAPI", "SQLAlchemy", "Redis"],
        }

        with patch(
            "services.react_agent.memory.get_l3_profile",
            new_callable=AsyncMock,
            return_value=mock_l3_profile,
        ):
            start = time.perf_counter()
            prompt = await assemble_system_prompt(db_session, user_id, resume.id)
            elapsed_ms = (time.perf_counter() - start) * 1000

        # 验证 prompt 包含 L3 画像和 L2 历史
        assert "Python 工程师" in prompt, "prompt 应包含 L3 画像"
        assert "历史问答" in prompt, "prompt 应包含 L2 历史"
        # SQLite in-memory + mock Redis，200ms 阈值有充足余量
        assert elapsed_ms < 200, (
            f"记忆装配延迟 {elapsed_ms:.1f}ms 超过 200ms 阈值"
        )


# ═══════════════════════════════════════════════════════════════
# L2: 并发压测
# ═══════════════════════════════════════════════════════════════


class TestL2ConcurrentStress:
    """L2: 并发压测（50 并发，P99 < 5s，全 mock）。

    通过 HTTP 客户端并发发起 50 个 /ask/agent 请求，测量 P99 延迟。
    所有 LLM 调用和 DB 写入操作均被 mock，只测量 HTTP + SSE + 循环编排开销。

    注意：AGENT_CONCURRENCY_LIMIT=5 限制了实际并发度，50 个请求会分批处理。
    但由于 mock LLM 即时返回，总耗时应远低于 5s。
    """

    @pytest.mark.asyncio
    async def test_concurrent_agent_requests(
        self,
        client: AsyncClient,
        auth_headers: dict,
        registered_user: dict,
        db_session,
    ):
        """50 个并发 Agent 请求，P99 延迟 < 5s。"""
        import services.react_agent.loop as loop_module

        user_id = registered_user["id"]
        resume = await _create_resume(db_session, user_id)

        # 重置 Semaphore（避免绑定到前一个测试的 event loop）
        loop_module._agent_semaphore = None

        # Mock 占位记录（避免 SQLite 并发写锁定）
        mock_placeholder = MagicMock()
        mock_placeholder.id = 1

        # 预填充 Redis 全局单例：get_redis() 每次调用会尝试连接 Redis 2s 才超时降级。
        # 50 并发 × 2s = 严重瓶颈。直接设置 _redis 为 InMemoryRedis，
        # 让 get_redis() 的 ping() 检查立即通过，返回 InMemoryRedis 实例。
        from core.redis_client import InMemoryRedis

        fast_redis = InMemoryRedis()
        # InMemoryRedis 缺少 exists 方法（is_token_revoked 会调），补上
        async def _mock_exists(key):
            return 0
        fast_redis.exists = _mock_exists

        # 并发下每次调用返回独立 generator（async generator 不可复用）
        stream_mock = MagicMock(
            side_effect=lambda *a, **k: _make_stream_response(content="并发测试答案")
        )

        with patch(
            "core.redis_client._redis", fast_redis,
        ), patch(
            "core.redis_client._in_memory", fast_redis,
        ), patch(
            "services.react_agent.loop.assemble_system_prompt",
            new_callable=AsyncMock,
        ) as mock_sys, patch(
            "services.react_agent.loop.check_quota",
            new_callable=AsyncMock,
        ) as mock_quota, patch(
            "services.react_agent.loop.llm_generate_with_tools",
            new_callable=AsyncMock,
        ) as mock_llm, patch(
            "services.react_agent.loop.llm_generate_with_tools_stream",
            stream_mock,
        ), patch(
            "services.react_agent.loop.get_agent_schemas",
            return_value=[],
        ), patch(
            "services.react_agent.loop.manage_l1_context",
        ) as mock_l1, patch(
            # patch core.database.AsyncSessionLocal 让 agent_stream 中的
            # stream_db 使用测试 DB engine，而非生产 engine（不可用）
            "core.database.AsyncSessionLocal",
            AsyncSessionTest,
        ), patch(
            # mock 占位记录写入，避免 50 并发 SQLite 写锁竞争
            "services.react_agent.streaming.save_qa_placeholder",
            new_callable=AsyncMock,
            return_value=mock_placeholder,
        ), patch(
            "services.react_agent.streaming.update_qa_answer",
            new_callable=AsyncMock,
            return_value=mock_placeholder,
        ):
            mock_sys.return_value = "system prompt"
            mock_quota.return_value = (True, None)
            mock_l1.side_effect = lambda msgs, **kw: msgs
            mock_llm.return_value = _make_llm_response(content="不应到达")

            CONCURRENCY = 50

            async def single_request() -> tuple[int, float]:
                """单个 Agent 请求，返回 (status_code, elapsed_ms)。"""
                start = time.perf_counter()
                resp = await client.post(
                    "/api/v1/qa/ask/agent",
                    json={
                        "resume_id": resume.id,
                        "question": "测试问题",
                    },
                    headers=auth_headers,
                )
                elapsed_ms = (time.perf_counter() - start) * 1000
                return resp.status_code, elapsed_ms

            # 并发发起 50 个请求
            results = await asyncio.gather(
                *[single_request() for _ in range(CONCURRENCY)]
            )

        status_codes = [r[0] for r in results]
        timings = sorted(r[1] for r in results)

        # 全部成功（status 200）
        failed = [sc for sc in status_codes if sc != 200]
        assert not failed, (
            f"{len(failed)}/{CONCURRENCY} 个请求失败，"
            f"状态码分布: { {sc: status_codes.count(sc) for sc in set(status_codes)} }"
        )

        # P99 计算：取排序后第 99 百分位的值
        p99_index = int(CONCURRENCY * 0.99)
        p99_ms = timings[p99_index]

        assert p99_ms < 5000, (
            f"P99 延迟 {p99_ms:.1f}ms 超过 5s 阈值"
            f"（min={timings[0]:.1f}ms, median={timings[CONCURRENCY // 2]:.1f}ms, "
            f"max={timings[-1]:.1f}ms）"
        )
