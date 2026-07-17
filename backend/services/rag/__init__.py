"""RAG 核心逻辑（阶段11 从 rag_service.py 拆分而来）。

拆分成四个内聚模块：
- clients.py   : 外部客户端单例（Chat / Embedding / Chroma）+ Chroma 簿记
- chunking.py  : 简历文本 → 结构化分块
- retrieval.py : 向量 / BM25 / 混合检索 / RRF / 重排 / 拒答判定
- pipeline.py  : 端到端编排（改写 → 检索 → 重排 → 生成 → 拒答）

`services/rag_service.py` 现在只是薄 re-export shim，保证旧 import 不破。
"""
