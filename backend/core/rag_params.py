"""RAG pipeline 可调参数集合，供 rag_tuning.evaluate 实验框架使用。

所有参数都有默认值（与当前 rag_service.py 硬编码一致），
实验时通过 dataclasses.replace() 覆盖即可。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RagParams:
    """RAG 流水线全部可调参数。

    默认值为去锚定基线（v2 二轮重审，综合 12 份简历 + 行业研究）：
    - chunk_size=300：12 份简历总体 median ≈ 245 字符，cs=300 覆盖约 60% 节段
    - rrf_k=60：RRF 论文原始默认值
    - rerank_final_top_k=3：适度精排保留数
    不沿用旧实验"最优"值——那些值在节段检测失效 + ChromaDB 并发 bug 下产生。
    """

    # ── 分块 ──
    chunk_size: int = 300  # 分块目标大小（字符），简历节段中位数 180
    overlap: int = 50  # 相邻块重叠字符数

    # ── 混合检索 ──
    dense_top_k: int = 25  # 稠密向量检索返回数（覆盖 cs=200 的最多 27 块）
    sparse_top_k: int = 25  # BM25 关键词检索返回数（确保 RRF 有足够候选池）
    hybrid_top_k: int = 10  # RRF 融合后保留数（上限 15，超出的都是重复）
    rrf_k: int = 60  # RRF 平滑常数（论文原始值 60）

    # ── Rerank 精排 ──
    rerank_input_top_k: int = 10  # 送入 Rerank 的候选数（从 hybrid 结果截断）
    rerank_final_top_k: int = 3  # Rerank 后保留数
    rerank_truncation: int = 400  # Rerank 输入截断长度（字符）

    # ── 拒答 ──
    reject_threshold: float = 0.3  # Rerank 最高分低于此值则拒答

    # ── 生成 ──
    generate_temperature: float = 0.3  # LLM 生成温度

    def validate(self) -> list[str]:
        """返回参数冲突列表，空列表 = 合法"""
        errors = []
        if self.overlap >= self.chunk_size:
            errors.append(f"overlap ({self.overlap}) must < chunk_size ({self.chunk_size})")
        if self.rerank_input_top_k != 0 and self.rerank_final_top_k > self.rerank_input_top_k:
            errors.append(
                f"rerank_final ({self.rerank_final_top_k}) must <= rerank_input ({self.rerank_input_top_k})"
            )
        if self.rerank_input_top_k > self.hybrid_top_k and self.rerank_input_top_k != 0:
            errors.append(
                f"rerank_input ({self.rerank_input_top_k}) must <= hybrid_top_k ({self.hybrid_top_k})"
            )
        if not (0.0 <= self.reject_threshold <= 1.0):
            errors.append(f"reject_threshold must be in [0, 1], got {self.reject_threshold}")
        if not (0.0 <= self.generate_temperature <= 2.0):
            errors.append(f"temperature must be in [0, 2], got {self.generate_temperature}")
        return errors


# 实验各阶段的参数网格（v2 P0 二轮重审后，综合多源数据）
# 数据基础：
#   - 6 份评测简历（技术岗：后端/前端/IoT/PM）：26 个节段，median=174，P75=302，max=631
#   - 6 份真实简历（运营/测试/运维/前端/测试）：23 个节段，median=397，P75=533，max=2290
#   - 12 份简历合计 49 个节段，覆盖泛 IT/运营/电商/测试多岗位
#   - 行业参考：arXiv 2407.19794（512 tokens 最优）、Polimi 2025（1500 chars 最佳）、
#     FloTorch 2026（recursive chunking 69% accuracy）、Elastic/Pinecone/Vespa（rrf_k=60）
# 设计原则：
#   - 不单独依赖任何一组简历，覆盖从短节段（资格证书 26 字符）到特长节段（实习 2290 字符）的完整范围
#   - 每档候选值有明确的物理意义，注释写明设计理由
PHASE1_GRID = {
    "chunk_size": [200, 300, 500],
    # 200: 6-18 块（跨 12 份简历），检索多样性最丰富
    # 300: 4-12 块，平衡型
    # 500: 2-8 块，粗粒度下界（少于 3 块时 dense/sparse 无差异）
    #
    # 去掉 800/1200：cs=800→2-4 块，cs=1200→1-3 块，块数太少时
    # dense 和 sparse 返回相同的候选集，RRF 融合和检索参数扫描失效。
    "overlap": [30, 60, 100],
    # 30: 最小边界保护（对 cs=200 ≈15%，对 cs=500 =6%）
    # 60: 行业 10-20% overlap 中值（对 cs=200 ≈30%，对 cs=500 ≈12%）
    # 100: 保守边界保护（对 cs=200 ≈50%，对 cs=500 ≈20%）
}

PHASE2_SWEEP = {
    "rrf_k": [10, 30, 60, 100, 200],
    # 10: 头部极度占优（dense rank1 权重是 rank10 的 1.8 倍）
    # 30: 温和头部优势
    # 60: RRF 论文原始默认值，Elastic/Pinecone/Vespa 全部使用
    # 100: 行业常见替代值
    # 200: 几乎扁平，排名几乎不影响融合（验证 k 的敏感性下限）
    "hybrid_top_k": [3, 5, 8, 12, 15],
    # 上限 15 而非 20/25：cs=200 时最多 18 块，cs=500 时最多 8 块。
    # 超过 15 后 dense/sparse 必然返回高度重叠的候选集，
    # hybrid_top_k 再大也只是重复消费同样的 chunk。
    # 3/5/8 对所有 chunk_size 都有意义；12/15 仅对 cs=200/300 有意义，
    # 对 cs=500 会退化为"全量返回"（但无害）。
    "rerank_truncation": [200, 0],
    # 200: 重截断——每块只留 200 字符给 reranker（测极简输入是否够用）
    # 0: 不截断——reranker 看到完整 chunk 内容
    # 去掉了 300/400/500：cs=200 时它们与 0 无区别（块≤200），
    # cs=300 时只有 200 有切割效果（33%），cs=500 时[200,0]已覆盖两端
}

PHASE3_GRID = {
    "rerank_input_top_k": [0, 3, 5, 8, 12],
    # 0: 哨兵值，跳过 Rerank，验证 Rerank 是否提升质量（phase ablation）
    # 3/5/8/12: 正常 Rerank 模式，必须 ≤ hybrid_top_k（约束校验拦截非法组合）。
    # 上限 12：cs=200 时最多 18 块，但 rerank 送入 12 条已覆盖 70%。
    "rerank_final_top_k": [2, 3, 5],
    # 2: 极度压缩，LLM 视野最窄
    # 3: 适度压缩基线
    # 5: 全面覆盖（对 cs=500 的 8 块已覆盖 >60%）
    # 去掉 8：cs=500 时最多 8 块，rerank→final 8 等价于"全量"，
    # 不提供与 5 的有意义区分。
}

PHASE4_THRESHOLDS = [0.2, 0.3, 0.4, 0.5, 0.6]
# 0.2: 几乎不拒（高召回低精度，适合探索性问题）
# 0.3: 中等宽松
# 0.4: 中等严格
# 0.5: 严格拒答
# 0.6: 极度严格（仅最高置信度的结果才回答）

PHASE6_TEMPERATURES = [0.0, 0.1, 0.3, 0.5]
# 0.0: 完全确定性，最适合 factual 类问题
# 0.1: 接近确定，极小随机性
# 0.3: 行业常见默认值，适合理性推理
# 0.5: 轻度创造性上限（超出后 hallucination 风险显著增加）
