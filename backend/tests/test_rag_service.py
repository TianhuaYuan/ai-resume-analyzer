"""
rag_service 单元测试 — 覆盖不依赖外部 API 的纯逻辑函数。

运行: python -m pytest tests/test_rag_service.py -v
"""

import pytest

from services.rag.chunking import chunk_by_sections, tokenize
from services.rag.pipeline import build_prompt
from services.rag.retrieval import _merge_results, reject_if_low_score

# ── 测试数据 ──────────────────────────────────────────────

SHORT_RESUME = """
个人信息
姓名：张三 | 电话：13800000000

教育背景
2018-2022  清华大学  计算机科学与技术  本科
GPA 3.8/4.0

专业技能
精通 Python、熟悉 FastAPI/Django 框架
""".strip()

LONG_SECTION_RESUME = """
个人信息
姓名：李四

工作经历
2020-2023  A公司 后端工程师。负责推荐系统后端开发，使用 Python + FastAPI 构建微服务架构。
设计了商品推荐 API，支持日均千万级调用。优化了 MySQL 慢查询，通过添加索引和查询重写将 P99 延迟从 800ms 降到 120ms。
参与了 Redis 集群从 3 节点到 6 节点的扩容，零宕机迁移完成。
搭建了基于 Prometheus + Grafana 的监控告警体系，覆盖 200+ 服务指标。
编写了 CI/CD 流水线，将部署时间从手动 30 分钟缩短到自动 3 分钟。
主导了从 Python 2 到 Python 3 的代码迁移，涉及 50 万行代码，零线上事故。
指导了 3 名实习生，其中 2 名转正。
""".strip()


MD_RESUME = """
## 个人信息
姓名：张三 | 邮箱: zhangsan@email.com

## 教育背景
2018-2022  清华大学  计算机科学与技术  本科
GPA 3.8/4.0，英语六级 528

## Work Experience
2022-2024  ByteDance  Software Engineer
Responsible for order fulfillment system development.

## 专业技能
精通 Python、Java、FastAPI、Spring Boot

## Projects
- Online Exam System: Spring Boot + Redis + RabbitMQ
- Blog Platform: Spring Boot + Thymeleaf

## Certifications
- AWS Certified Solutions Architect
- 全国大学生算法竞赛铜奖

## 自我评价
热爱技术，持续学习。
""".strip()

ENGLISH_RESUME = """
SUMMARY
Senior software engineer with 8 years of experience in backend systems.

EDUCATION
Master of Science in Computer Science, Zhejiang University, 2018

Work Experience
Company A - Senior Engineer (2020-present)
Led the architecture redesign of the payment system.

Technical Skills
Java, Python, Go, Kubernetes, Docker, Redis

PROJECTS
- Payment Gateway: Designed high-throughput payment processing system
- Monitoring Platform: Built Prometheus + Grafana stack

Certifications
- AWS Solutions Architect Professional

PUBLICATIONS
- Paper on distributed systems at IEEE TPDS
""".strip()

# ── chunk_by_sections ────────────────────────────────────


class TestChunkBySections:
    def test_short_resume_one_chunk_per_section(self):
        """短简历：每个节段不足 chunk_size，不触发细分"""
        chunks = chunk_by_sections(SHORT_RESUME, chunk_size=500)
        sections = {c["section"] for c in chunks}
        # "个人信息" 不在 SECTION_HEADERS 里，会被归入"基本信息"
        assert "基本信息" in sections
        assert "教育背景" in sections
        assert "专业技能" in sections
        # 每个 chunk 应标注所属节段
        for c in chunks:
            assert len(c["text"]) <= 500
            assert "section" in c
            assert "chunk_index" in c

    def test_chunk_indices_sequential(self):
        """chunk_index 应从 0 递增"""
        chunks = chunk_by_sections(SHORT_RESUME, chunk_size=500)
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_long_section_triggers_recursive_split(self):
        """长节段超过 chunk_size 应触发递归细分"""
        chunks = chunk_by_sections(LONG_SECTION_RESUME, chunk_size=200)
        work_chunks = [c for c in chunks if c["section"] == "工作经历"]
        assert len(work_chunks) > 1, f"期望工作经历被细分为多个 chunk，实际 {len(work_chunks)} 个"

    def test_empty_text(self):
        """空文本应返回空列表"""
        chunks = chunk_by_sections("", chunk_size=500)
        assert chunks == []

    def test_no_section_headers(self):
        """无节段标题的纯文本应全部归入'正文'"""
        text = "这是一段没有任何简历标题的纯文本内容。"
        chunks = chunk_by_sections(text, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0]["section"] == "正文"

    def test_chunk_size_respected(self):
        """每个 chunk 不应超过 chunk_size（允许少量超出因为分隔符后移）"""
        chunks = chunk_by_sections(LONG_SECTION_RESUME, chunk_size=300)
        for c in chunks:
            # 由于分隔符查找可能略超，给 30% 容忍度
            assert (
                len(c["text"]) <= 300 * 1.3
            ), f"chunk idx={c['chunk_index']} 长度 {len(c['text'])} 远超 300"

    def test_markdown_section_detection(self):
        """Markdown 格式的节段 (## 教育背景) 应被正确识别并保留节段名"""
        chunks = chunk_by_sections(MD_RESUME, chunk_size=500)
        sections = {c["section"] for c in chunks}
        assert "教育背景" in sections, f"Markdown 中文节段未被识别，实际有: {sections}"
        assert "Work Experience" in sections, f"Markdown 英文节段未被识别，实际有: {sections}"
        assert "Projects" in sections, f"Markdown Projects 节段未被识别，实际有: {sections}"
        assert (
            "Certifications" in sections
        ), f"Markdown Certifications 节段未被识别，实际有: {sections}"

    def test_english_section_detection(self):
        """纯英文简历的节段（含全大写形式如 SUMMARY/EDUCATION）应被正确识别"""
        chunks = chunk_by_sections(ENGLISH_RESUME, chunk_size=500)
        sections = {c["section"] for c in chunks}
        # 节段名保留原文格式（SUMMARY 全大写即 "SUMMARY"）
        assert "SUMMARY" in sections, f"未识别 SUMMARY 节段: {sections}"
        assert "EDUCATION" in sections, f"未识别 EDUCATION 节段: {sections}"
        assert "Work Experience" in sections, f"未识别工作经历节段: {sections}"
        assert "Technical Skills" in sections or "Skills" in sections, f"未识别技能节段: {sections}"
        assert "Certifications" in sections, f"未识别 Certifications 节段: {sections}"
        # 所有节段都被识别，无遗漏
        assert len(sections) >= 7, f"期望至少 7 个节段，实际 {len(sections)}: {sections}"

    def test_mixed_format_no_false_positive(self):
        """纯文本行首的普通句子不应被误判为节段标题"""
        text = """
        这是一段普通介绍。
        Skills development is essential for career growth.
        教育背景很重要但不是标题。
        Education system in China has unique characteristics.
        """
        chunks = chunk_by_sections(text.strip(), chunk_size=500)
        # 以上应全部归入"正文"，因为"教育背景"后跟的不是换行而是"很重要"
        assert len(chunks) == 1
        assert chunks[0]["section"] == "正文"

    def test_plain_text_header_without_markdown(self):
        """纯文本格式的中文节段（不加 ##）仍需正常识别"""
        chunks = chunk_by_sections(SHORT_RESUME, chunk_size=500)
        sections = {c["section"] for c in chunks}
        assert "教育背景" in sections

    def test_all_caps_english_header(self):
        """全大写英文节段如 SUMMARY、EDUCATION 应被识别（节段名保留原文格式）"""
        text = "SUMMARY\n5 years experience\n\nEDUCATION\nTsinghua University"
        chunks = chunk_by_sections(text, chunk_size=500)
        sections = {c["section"] for c in chunks}
        assert "SUMMARY" in sections, f"全大写 SUMMARY 未被识别: {sections}"
        assert "EDUCATION" in sections, f"全大写 EDUCATION 未被识别: {sections}"
        # 文本以 SUMMARY 开头，无前导文本 → 不出 "基本信息"（空段被跳过）
        assert len(sections) == 2, f"期望 2 个节段（SUMMARY+EDUCATION），实际 {sections}"


# ── build_prompt ─────────────────────────────────────────


class TestBuildPrompt:
    def test_basic_structure(self):
        chunks = ["张三精通 Python", "他有 3 年工作经验"]
        prompt = build_prompt(chunks, "他会 Python 吗？")
        assert "system" in prompt
        assert "user" in prompt
        assert "简历分析助手" in prompt["system"]
        assert "编造事实" in prompt["system"]
        assert "张三精通 Python" in prompt["user"]
        assert "他会 Python 吗？" in prompt["user"]

    def test_empty_chunks(self):
        prompt = build_prompt([], "测试问题")
        # 不应崩溃，但不含任何 chunk 内容
        assert "段落" not in prompt["user"] or "[段落 1]" not in prompt["user"]

    def test_paragraph_numbering(self):
        chunks = ["A", "B", "C"]
        prompt = build_prompt(chunks, "问题")
        assert "[段落 1]" in prompt["user"]
        assert "[段落 2]" in prompt["user"]
        assert "[段落 3]" in prompt["user"]


# ── reject_if_low_score ──────────────────────────────────


class TestRejectIfLowScore:
    def test_all_low_scores_reject(self):
        chunks = [
            {"rerank_score": 0.1},
            {"rerank_score": 0.3},
            {"rerank_score": 0.4},
        ]
        assert reject_if_low_score(chunks, threshold=0.5) is True

    def test_one_high_score_pass(self):
        chunks = [
            {"rerank_score": 0.1},
            {"rerank_score": 0.8},
            {"rerank_score": 0.3},
        ]
        assert reject_if_low_score(chunks, threshold=0.5) is False

    def test_exact_threshold(self):
        chunks = [{"rerank_score": 0.5}]
        # 0.5 >= 0.5 → 通过
        assert reject_if_low_score(chunks, threshold=0.5) is False
        # 0.49 < 0.5 → 拒答
        assert reject_if_low_score([{"rerank_score": 0.49}], threshold=0.5) is True

    def test_empty_chunks_reject(self):
        assert reject_if_low_score([], threshold=0.5) is True

    def test_missing_rerank_score(self):
        chunks = [{"text": "no score field"}]
        # 缺少 rerank_score → 未经过 rerank → 不拒答（保留结果）
        assert reject_if_low_score(chunks, threshold=0.5) is False


# ── P0.5: rerank() 空 results 降级测试 ──────────────────


class TestRerankEmptyResultsFallback:
    """P0.5: Rerank API HTTP 200 + 空 results 时应走降级路径（与 API 失败一致）。

    修复前：空 results → score_map={} → 所有 chunk rerank_score=0.0
            → reject_if_low_score 判定 0.0 < 0.3 → 误拒答
    修复后：空 results 视为异常，返回 rerank_score=0.5 的降级副本（同 API 失败路径）
    """

    @pytest.mark.asyncio
    async def test_empty_results_falls_back_to_neutral_score(self, monkeypatch):
        from services.rag import retrieval as retrieval_mod

        # 构造 8 个 chunks（> top_k=5 才会真正进入 rerank API 路径）
        chunks = [{"text": f"chunk_{i}"} for i in range(8)]

        # mock with_retry 直接返回 {"output": {"results": []}}（HTTP 200 但 results 为空）
        async def _fake_with_retry(*args, **kwargs):
            return {"output": {"results": []}}

        monkeypatch.setattr(retrieval_mod, "with_retry", _fake_with_retry)

        result = await retrieval_mod.rerank("test question", chunks, top_k=5)

        # 修复后：应返回降级路径的 0.5 分（而非 0.0）
        assert len(result) == 5
        for c in result:
            assert c["rerank_score"] == 0.5, f"expected 0.5 fallback, got {c.get('rerank_score')}"

    @pytest.mark.asyncio
    async def test_empty_results_does_not_trigger_reject(self, monkeypatch):
        """端到端验证：空 results → 降级 0.5 → reject_if_low_score(0.3) 不拒答。"""
        from services.rag import retrieval as retrieval_mod

        chunks = [{"text": f"chunk_{i}"} for i in range(8)]

        async def _fake_with_retry(*args, **kwargs):
            return {"output": {"results": []}}

        monkeypatch.setattr(retrieval_mod, "with_retry", _fake_with_retry)

        result = await retrieval_mod.rerank("q", chunks, top_k=5)
        # 修复后不应触发拒答（0.5 >= 0.3）
        assert retrieval_mod.reject_if_low_score(result, threshold=0.3) is False


# ── _merge_results (RRF) ────────────────────────────────


class TestMergeResults:
    def test_dense_only(self):
        dense = [
            {"chunk_index": 0, "text": "A", "score": 0.9, "source": "dense"},
            {"chunk_index": 1, "text": "B", "score": 0.7, "source": "dense"},
        ]
        merged = _merge_results(dense, [], top_k=5)
        assert len(merged) == 2
        assert merged[0]["chunk_index"] == 0  # 分数高的排前面

    def test_sparse_only(self):
        sparse = [
            {"chunk_index": 3, "text": "C", "score": 5.0, "source": "sparse"},
        ]
        merged = _merge_results([], sparse, top_k=5)
        assert len(merged) == 1

    def test_same_chunk_both_lists_boosted(self):
        """同一 chunk 在两路都命中 → RRF 累加得分 → 应排更前"""
        dense = [
            {"chunk_index": 0, "text": "A", "score": 0.9, "source": "dense"},
            {"chunk_index": 1, "text": "B", "score": 0.7, "source": "dense"},
        ]
        sparse = [
            {"chunk_index": 1, "text": "B", "score": 5.0, "source": "sparse"},
            {"chunk_index": 2, "text": "C", "score": 3.0, "source": "sparse"},
        ]
        merged = _merge_results(dense, sparse, top_k=5)
        # chunk 1 在两路都命中，应有更高 RRF 分数
        assert merged[0]["chunk_index"] == 1
        # chunk 0 只在 dense，chunk 2 只在 sparse
        indices = [c["chunk_index"] for c in merged]
        assert 0 in indices
        assert 2 in indices

    def test_top_k_truncation(self):
        dense = [
            {"chunk_index": i, "text": str(i), "score": 0.5, "source": "dense"} for i in range(10)
        ]
        merged = _merge_results(dense, [], top_k=3)
        assert len(merged) == 3

    def test_rrf_k_parameter(self):
        """k=60 (论文常用值) 保证合理排序"""
        dense = [
            {"chunk_index": i, "text": str(i), "score": 0.5, "source": "dense"} for i in range(5)
        ]
        merged = _merge_results(dense, [], top_k=5, k=60)
        assert len(merged) == 5
        # 排名应保持输入顺序（同源时 RRF 分数就是 1/(k+rank+1) 递减）
        assert merged[0]["chunk_index"] == 0


# ── tokenize ────────────────────────────────────────────


class TestTokenize:
    def test_chinese_tokenization(self):
        tokens = tokenize("精通Python和FastAPI框架")
        assert "Python" in tokens or "python" in tokens
        assert "精通" in tokens
        assert len(tokens) > 2  # jieba 应该切开

    def test_english_preserved(self):
        tokens = tokenize("FastAPI MySQL Redis")
        # jieba 保留原始大小写
        assert "FastAPI" in tokens
        assert "MySQL" in tokens

    def test_empty_string(self):
        tokens = tokenize("")
        assert tokens == []


# ── chunk_by_sections 边界场景 ────────────────────────────


class TestChunkEdgeCases:
    def test_overlap_between_sub_chunks(self):
        """验证 overlap：递归细分时相邻 sub-chunk 应有重叠"""
        # 构造刚好超过 chunk_size 的文本
        text = "工作经历\n" + "A" * 550  # 工作经历节段 550 字符
        chunks = chunk_by_sections(text, chunk_size=500, overlap=50)
        work_chunks = [c for c in chunks if c["section"] == "工作经历"]
        if len(work_chunks) >= 2:
            c0_end = work_chunks[0]["text"][-50:]
            c1_start = work_chunks[1]["text"][:50]
            assert c0_end == c1_start, "相邻 sub-chunk 应有 overlap"

    def test_metadata_fields_present(self):
        chunks = chunk_by_sections(SHORT_RESUME)
        for c in chunks:
            assert "text" in c
            assert "section" in c
            assert "chunk_index" in c
            assert "start_char" in c
            assert "end_char" in c
            assert c["end_char"] > c["start_char"]
