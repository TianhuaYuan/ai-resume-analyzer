"""VectorStore 协议的 Chroma 实现。

Chroma PersistentClient 非线程安全，所有操作经 services.rag.clients.with_chroma
（全局锁 + asyncio.to_thread）串行化，避免并发读写损坏 HNSW 索引（Bug 3）。

本实现尽量薄：只做"集合不存在 → None/空/忽略"的归一化与结果解包，
不掺入任何业务/检索逻辑（RRF、分块、过滤都留在应用层，见 D4/D9）。
"""

import logging
from typing import Any

from services.rag.clients import get_chroma_client, with_chroma

logger = logging.getLogger(__name__)


class ChromaAdapter:
    """ChromaDB 适配器：与既有 process_resume 语义保持一致。"""

    @staticmethod
    def _normalize_where(where: dict[str, Any] | None) -> dict[str, Any] | None:
        """把多顶层字段 where 归一化为 Chroma 的 ``$and`` 语法。

        Chroma 要求 where 顶层只能有一个操作符（``$and``/``$or``/``$not``）
        或单字段简写。业务层（build_scope_where / index_asset 退役查询等）
        惯用 ``{field1: v1, field2: v2}`` 双字段顶层写法，在此统一适配。
        """
        if not where:
            return where
        # 已是复合操作符，原样透传
        if any(op in where for op in ("$and", "$or", "$not")):
            return where
        # 单字段（含值内嵌 $in 等）原样
        if len(where) == 1:
            return where
        # 多顶层字段 → 包成 $and
        return {"$and": [{k: v} for k, v in where.items()]}

    async def get(
        self,
        collection: str,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        def _sync() -> dict[str, Any] | None:
            try:
                coll = get_chroma_client().get_collection(collection)
            except Exception:
                return None
            return coll.get(where=self._normalize_where(where), include=["documents", "metadatas"])

        data = await with_chroma(_sync)
        if data is None:
            return None
        ids: list[str] = data.get("ids", []) or []
        documents: list[str] = data.get("documents", []) or []
        metadatas: list[dict] = data.get("metadatas", []) or []
        return [
            {"id": cid, "text": doc, "metadata": meta or {}}
            for cid, doc, meta in zip(ids, documents, metadatas)
        ]

    async def query(
        self,
        collection: str,
        embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        def _sync() -> dict[str, Any] | None:
            try:
                coll = get_chroma_client().get_collection(collection)
            except Exception:
                return None
            return coll.query(
                query_embeddings=[embedding],
                n_results=top_k,
                where=self._normalize_where(where),
                include=["documents", "metadatas", "distances"],
            )

        results = await with_chroma(_sync)
        if results is None:
            return []

        chunks: list[dict[str, Any]] = []
        ids = results.get("ids", [[]])[0]
        for i in range(len(ids)):
            meta = results["metadatas"][0][i] or {}
            chunks.append(
                {
                    "id": ids[i],
                    "text": results["documents"][0][i],
                    "metadata": meta,
                    # cosine distance 0..2 → similarity -1..1
                    "score": 1.0 - results["distances"][0][i],
                }
            )
        return chunks

    async def upsert(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        def _sync() -> None:
            coll = get_chroma_client().get_or_create_collection(
                name=collection, metadata={"hnsw:space": "cosine"}
            )
            coll.add(
                ids=[str(i) for i in ids],
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )

        await with_chroma(_sync)

    async def update_metadata(
        self,
        collection: str,
        ids: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        def _sync() -> None:
            try:
                coll = get_chroma_client().get_collection(collection)
            except ValueError:
                return
            coll.update(
                ids=[str(i) for i in ids],
                metadatas=metadatas,
            )

        await with_chroma(_sync)

    async def delete(self, collection: str, where: dict[str, Any]) -> None:
        def _sync() -> None:
            try:
                coll = get_chroma_client().get_collection(collection)
            except ValueError:
                return  # collection 不存在，忽略
            coll.delete(where=self._normalize_where(where))

        await with_chroma(_sync)

    async def delete_collection(self, collection: str) -> None:
        def _sync() -> None:
            # 只吞"集合不存在"（ValueError）；真实连接错误向上传播，
            # 让调用方（如 clear_resume_vectors）能触发 reconnect_chroma 恢复
            try:
                get_chroma_client().delete_collection(collection)
            except ValueError:
                pass

        await with_chroma(_sync)
