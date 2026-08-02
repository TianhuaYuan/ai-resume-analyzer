"""向量存储端口：最小能力面。

所有方法均为 async，内部自行处理线程安全/并发控制
（Chroma PersistentClient 非线程安全，由 adapter 经全局锁串行化）。
"""

from typing import Any, Protocol


class VectorStore(Protocol):
    """向量存储的最小读写能力面。

    业务代码（检索/索引/分块服务）只依赖此协议，不绑定任何具体向量库。
    """

    async def get(
        self,
        collection: str,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        """读取集合全部条目（支持 metadata 过滤）。

        Returns:
            ``[{id, text, metadata}, ...]``；集合不存在返回 ``None``。
        """
        ...

    async def query(
        self,
        collection: str,
        embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """按向量相似度检索。

        Returns:
            ``[{id, text, metadata, score}, ...]``，``score`` 为相似度（1.0 最相似）；
            集合不存在返回 ``[]``。
        """
        ...

    async def upsert(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """集合不存在则创建，然后批量写入（同 id 覆盖）。"""
        ...

    async def update_metadata(
        self,
        collection: str,
        ids: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """按 id 批量替换元数据（ids 与 metadatas 等长对齐），不改变向量/文本。

        用于版本化置位（旧版本 chunks 的 ``is_latest`` 翻转为 False，D2）；
        集合不存在则忽略。
        """
        ...

    async def delete(self, collection: str, where: dict[str, Any]) -> None:
        """按 metadata 条件删除（集合不存在则忽略）。"""
        ...

    async def delete_collection(self, collection: str) -> None:
        """删除整个集合（不存在则忽略）。"""
        ...
