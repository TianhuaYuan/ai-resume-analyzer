"""RAG pipeline 可调参数集合，供 rag_tuning.evaluate 实验框架使用。

所有参数都有默认值（与当前 rag_service.py 硬编码一致），
实验时通过 dataclasses.replace() 覆盖即可。
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RagParams:
    """RAG 流水线全部可调参数"""

    # ── 分块 ──
    chunk_size: int = 1200      # 分块目标大小（字符）
    overlap: int = 50           # 相邻块重叠字符数

    # ── 混合检索 ──
    dense_top_k: int = 20       # 稠密向量检索返回数
    sparse_top_k: int = 20      # BM25 关键词检索返回数
    hybrid_top_k: int = 20      # RRF 融合后保留数
    rrf_k: int = 100            # RRF 平滑常数

    # ── Rerank 精排 ──
    rerank_input_top_k: int = 20    # 送入 Rerank 的候选数（= hybrid_top_k）
    rerank_final_top_k: int = 5     # Rerank 后保留数
    rerank_truncation: int = 400    # Rerank 输入截断长度（字符）

    # ── 拒答 ──
    reject_threshold: float = 0.3   # Rerank 最高分低于此值则拒答

    # ── 生成 ──
    generate_temperature: float = 0.3  # LLM 生成温度（Phase 5 修正：多参数组合下 0.3 优于 0.1）⚠️ 依赖 Chat 模型，换模型后需重测

    def validate(self) -> list[str]:
        """返回参数冲突列表，空列表 = 合法"""
        errors = []
        if self.overlap >= self.chunk_size:
            errors.append(f"overlap ({self.overlap}) must < chunk_size ({self.chunk_size})")
        if self.rerank_final_top_k > self.rerank_input_top_k:
            errors.append(f"rerank_final ({self.rerank_final_top_k}) must <= rerank_input ({self.rerank_input_top_k})")
        if self.rerank_input_top_k > self.hybrid_top_k:
            errors.append(f"rerank_input ({self.rerank_input_top_k}) must <= hybrid_top_k ({self.hybrid_top_k})")
        if not (0.0 <= self.reject_threshold <= 1.0):
            errors.append(f"reject_threshold must be in [0, 1], got {self.reject_threshold}")
        if not (0.0 <= self.generate_temperature <= 2.0):
            errors.append(f"temperature must be in [0, 2], got {self.generate_temperature}")
        return errors


# 实验各阶段的参数网格
PHASE1_GRID = {
    "chunk_size": [300, 500, 800, 1200],
    "overlap":    [0, 50, 100, 150],
}

PHASE2_SWEEP = {
    "rrf_k":              [10, 30, 60, 100, 200],
    "hybrid_top_k":       [10, 15, 20, 30, 40],
    "rerank_truncation":  [200, 300, 400, 500, 0],  # 0 = 不截断
}

PHASE3_GRID = {
    "rerank_input_top_k":  [15, 20, 30],
    "rerank_final_top_k":  [3, 5, 8, 10],
}

PHASE4_THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

PHASE6_TEMPERATURES = [0.0, 0.1, 0.3]
