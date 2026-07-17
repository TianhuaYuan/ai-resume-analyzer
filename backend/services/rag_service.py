"""rag_service 兼容 shim（阶段11 重构后）。

历史版本：所有 RAG 逻辑集中在本文件（~720 行），被大量模块 import
（mcp_server/tools/*、services/agentic_rag/*、api/resumes.py、api/qa.py、各测试等）。

阶段11 已把逻辑拆分为内聚模块：
    services/rag/clients.py   外部客户端单例 + Chroma 簿记
    services/rag/chunking.py  结构化分块
    services/rag/retrieval.py 向量/BM25/混合检索/RRF/重排/拒答
    services/rag/pipeline.py  端到端编排 + LLM 生成

为避免改动任何 importer，本文件保留为"薄 re-export shim"：
所有公开符号仍可从 `services.rag_service` 导入，行为与拆分前完全一致。
新增代码请直接 `from services.rag.xxx import ...`。

⚠️ 若后续要彻底移除本 shim：全局替换 `services.rag_service` →
   `services.rag.clients|chunking|retrieval|pipeline` 对应模块即可。
"""
from services.rag.clients import (
    _collection_name,
    _cleanup_orphan_segments,
    get_chat_client,
    get_chroma_client,
    get_embedding_client,
    reconnect_chroma,
)
from services.rag.chunking import (
    SECTION_HEADERS,
    SECTION_PATTERN,
    _find_split,
    _make_chunk,
    _recursive_split,
    _split_by_sections,
    _tokenize,
    chunk_by_sections,
    fixed_chunk,
)
from services.rag.retrieval import (
    _bm25_indexes,
    _bm25_lock,
    _keyword_search,
    _load_bm25_index,
    _merge_results,
    _vector_search,
    get_embeddings,
    hybrid_search,
    hybrid_search_p,
    rerank,
    rerank_p,
    reject_if_low_score,
)
from services.rag.pipeline import (
    FALLBACK_MESSAGE,
    _llm_generate_stream,
    _retrieve,
    _retrieve_p,
    ask_question,
    ask_question_p,
    ask_question_stream,
    build_prompt,
    clear_resume_vectors,
    llm_generate,
    process_resume,
    rewrite_query,
)

__all__ = [
    # clients
    "get_chat_client", "get_embedding_client", "get_chroma_client",
    "reconnect_chroma", "_collection_name", "_cleanup_orphan_segments",
    # chunking
    "SECTION_HEADERS", "SECTION_PATTERN", "_tokenize", "_split_by_sections",
    "_find_split", "_recursive_split", "_make_chunk", "chunk_by_sections", "fixed_chunk",
    # retrieval
    "get_embeddings", "_load_bm25_index", "_keyword_search", "_vector_search",
    "hybrid_search", "hybrid_search_p", "_merge_results", "rerank", "rerank_p",
    "reject_if_low_score", "_bm25_indexes", "_bm25_lock",
    # pipeline
    "FALLBACK_MESSAGE", "rewrite_query", "llm_generate", "_llm_generate_stream",
    "build_prompt", "process_resume", "_retrieve", "_retrieve_p", "ask_question",
    "ask_question_p", "ask_question_stream", "clear_resume_vectors",
]
