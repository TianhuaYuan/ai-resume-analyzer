"""向量存储端口层（可移植性边界，D9）。

- ``ports.VectorStore``：业务代码唯一依赖的协议
- ``ChromaAdapter``：当前唯一实现（薄封装 services.rag.clients 的 Chroma 单例）
- ``get_vector_store()``：单例工厂。未来换 Qdrant/Milvus 时只改这里 + 新增一个 adapter，
  业务代码（retrieval / chunks_service / pipeline）零改动。
"""

from services.vector_store.chroma_adapter import ChromaAdapter
from services.vector_store.ports import VectorStore

_vector_store: ChromaAdapter | None = None


def get_vector_store() -> VectorStore:
    """获取向量存储单例（Protocol 类型，业务层感知不到具体实现）。"""
    global _vector_store
    if _vector_store is None:
        _vector_store = ChromaAdapter()
    return _vector_store


__all__ = ["VectorStore", "ChromaAdapter", "get_vector_store"]
