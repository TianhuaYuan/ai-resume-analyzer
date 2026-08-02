"""版本化索引器单元测试（全 mock，绝不碰真实 Chroma）。

背景：测试环境共享真实 Chroma 持久目录，并发会损坏 HNSW 索引（Bug 3）。
因此本测试：
- 用内存 ``FakeVectorStore`` 实现 VectorStore 协议（dict 存储），替换真实单例；
- 用 ``patch("services.rag.indexer.get_embeddings")`` 返回固定维度假向量；
- 不触发任何 embedding API / Chroma 网络 IO。

运行: python -m pytest tests/test_indexer.py -q
"""

from copy import deepcopy
from unittest.mock import patch

import pytest

from services.rag.indexer import index_asset
from services.rag.metadata import (
    META_ASSET_ID,
    META_ASSET_TYPE,
    META_CHUNK_INDEX,
    META_IS_LATEST,
    META_USER_ID,
    META_VERSION,
)

SAMPLE_TEXT = """
个人信息
姓名：张三 | 电话：13800000000

教育背景
2018-2022  清华大学  计算机科学与技术  本科

专业技能
精通 Python、熟悉 FastAPI/Django 框架
""".strip()


class FakeVectorStore:
    """内存 VectorStore：``collection -> {id: {text, embedding, metadata}}``。

    与 chroma_adapter 语义对齐：
    - ``get``：集合不存在返回 None（可带 metadata 过滤）；
    - ``upsert``：集合不存在自动创建，同 id 覆盖；
    - ``update_metadata``：按 id 替换 metadata，不改变向量/文本。
    """

    def __init__(self) -> None:
        self._collections: dict[str, dict[str, dict]] = {}

    @staticmethod
    def _match(metadata: dict, where: dict | None) -> bool:
        if not where:
            return True
        return all(metadata.get(k) == v for k, v in where.items())

    async def get(self, collection: str, where: dict | None = None) -> list[dict] | None:
        coll = self._collections.get(collection)
        if coll is None:
            return None
        return [
            {"id": cid, "text": rec["text"], "metadata": deepcopy(rec["metadata"])}
            for cid, rec in coll.items()
            if self._match(rec["metadata"], where)
        ]

    async def query(
        self,
        collection: str,
        embedding: list[float],
        top_k: int,
        where: dict | None = None,
    ) -> list[dict]:
        coll = self._collections.get(collection)
        if coll is None:
            return []
        hits = [
            {
                "id": cid,
                "text": rec["text"],
                "metadata": deepcopy(rec["metadata"]),
                "score": 1.0,  # 测试不依赖真实相似度计算
            }
            for cid, rec in coll.items()
            if self._match(rec["metadata"], where)
        ]
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_k]

    async def upsert(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        coll = self._collections.setdefault(collection, {})
        for cid, doc, emb, meta in zip(ids, documents, embeddings, metadatas):
            coll[cid] = {"text": doc, "embedding": emb, "metadata": deepcopy(meta)}

    async def update_metadata(
        self,
        collection: str,
        ids: list[str],
        metadatas: list[dict],
    ) -> None:
        coll = self._collections.get(collection)
        if coll is None:
            return  # 集合不存在则忽略（与 chroma_adapter 一致）
        for cid, meta in zip(ids, metadatas):
            if cid in coll:
                coll[cid]["metadata"] = deepcopy(meta)

    async def delete(self, collection: str, where: dict) -> None:
        coll = self._collections.get(collection)
        if coll is None:
            return
        for cid in [c for c, r in coll.items() if self._match(r["metadata"], where)]:
            del coll[cid]

    async def delete_collection(self, collection: str) -> None:
        self._collections.pop(collection, None)

    def chunks(self, collection: str) -> dict[str, dict]:
        """测试辅助：直接读取某集合的全部 ``{id: rec}``（含 text/embedding/metadata）。"""
        return self._collections.get(collection, {})


async def _fake_get_embeddings(texts: list[str], resume_id: int | None = None) -> list[list[float]]:
    """固定 8 维假向量；维度与内容无关，仅用于通过 upsert 参数校验。"""
    return [[0.1] * 8 for _ in texts]


@pytest.fixture
def fake_store() -> FakeVectorStore:
    """内存向量库 + 替换单例 + 替换 embedding，一次备齐，绝不碰真实 Chroma。"""
    store = FakeVectorStore()
    with (
        patch("services.rag.indexer.get_vector_store", return_value=store),
        patch("services.rag.indexer.get_embeddings", new=_fake_get_embeddings),
    ):
        yield store


async def _index_v1(fake_store: FakeVectorStore, collection: str, asset_id: int, user_id: int = 1):
    """辅助：用默认样本索引 v1。"""
    return await index_asset(
        collection=collection,
        user_id=user_id,
        asset_id=asset_id,
        asset_type="resume",
        text=SAMPLE_TEXT,
        version=1,
    )


@pytest.mark.asyncio
async def test_index_asset_writes_new_version(fake_store):
    """首次索引：写入正确 metadata（asset_id/version/is_latest=True）并返回 chunk 数。"""
    asset_id, version, user_id = 42, 1, 7
    n = await index_asset(
        collection="resume_42",
        user_id=user_id,
        asset_id=asset_id,
        asset_type="resume",
        text=SAMPLE_TEXT,
        version=version,
    )

    assert n > 0
    chunks = fake_store.chunks("resume_42")
    assert len(chunks) == n

    for cid, rec in chunks.items():
        meta = rec["metadata"]
        # chunk id 格式：{asset_type}_{asset_id}_v{version}_{chunk_index}
        assert cid == f"resume_{asset_id}_v{version}_{meta[META_CHUNK_INDEX]}"
        assert meta[META_ASSET_ID] == asset_id
        assert meta[META_ASSET_TYPE] == "resume"
        assert meta[META_USER_ID] == user_id
        assert meta[META_VERSION] == version
        assert meta[META_IS_LATEST] is True
        # 假向量已写入（通过 upsert 参数校验）
        assert rec["embedding"] == [0.1] * 8


@pytest.mark.asyncio
async def test_index_asset_retires_old_version(fake_store):
    """同 asset 索引 v2 后：v1 chunks is_latest 置 False，v2 为 True，v1 仍可查（版本保留）。"""
    collection = "resume_9"
    await _index_v1(fake_store, collection, asset_id=9)
    await index_asset(
        collection=collection,
        user_id=1,
        asset_id=9,
        asset_type="resume",
        text=SAMPLE_TEXT,
        version=2,
    )

    v1 = await fake_store.get(collection, where={META_ASSET_ID: 9, META_VERSION: 1})
    v2 = await fake_store.get(collection, where={META_ASSET_ID: 9, META_VERSION: 2})

    # 版本保留：v1 chunks 仍在（可查旧版本）
    assert len(v1) > 0
    assert len(v2) > 0
    # v1 已退役，v2 标记为最新
    assert all(item["metadata"][META_IS_LATEST] is False for item in v1)
    assert all(item["metadata"][META_IS_LATEST] is True for item in v2)
    # 全局同一 asset 只应有一版 is_latest=True 的快照（= v2 的 chunk 数）
    latest = await fake_store.get(collection, where={META_ASSET_ID: 9, META_IS_LATEST: True})
    assert len(latest) == len(v2)


@pytest.mark.asyncio
async def test_index_asset_idempotent_chunk_ids(fake_store):
    """chunk id 携带版本号：v2 的 id 与 v1 不重叠，互不覆盖。"""
    collection = "resume_5"
    await _index_v1(fake_store, collection, asset_id=5)
    await index_asset(
        collection=collection,
        user_id=1,
        asset_id=5,
        asset_type="resume",
        text=SAMPLE_TEXT,
        version=2,
    )

    chunks = fake_store.chunks(collection)
    v1_ids = [cid for cid in chunks if "_v1_" in cid]
    v2_ids = [cid for cid in chunks if "_v2_" in cid]

    assert v1_ids and v2_ids
    assert set(v1_ids).isdisjoint(set(v2_ids)), "v1/v2 chunk id 不应重叠"
    assert all(cid.startswith("resume_5_v2_") for cid in v2_ids)
    # 每个 chunk_index 都有 v1+v2 两个独立条目（共 2×n），无覆盖丢失
    assert len(v1_ids) == len(v2_ids)
    assert len(chunks) == len(v1_ids) + len(v2_ids)


@pytest.mark.asyncio
async def test_index_asset_empty_text(fake_store):
    """空文本：返回 0，不创建集合、不写任何条目。"""
    n = await index_asset(
        collection="c_empty",
        user_id=1,
        asset_id=1,
        asset_type="resume",
        text="",
        version=1,
    )
    assert n == 0
    assert "c_empty" not in fake_store._collections
    assert fake_store.chunks("c_empty") == {}


@pytest.mark.asyncio
async def test_index_asset_nonexistent_collection(fake_store):
    """collection 不存在时首次索引也能正常创建并写入。"""
    collection = "brand_new"
    n = await index_asset(
        collection=collection,
        user_id=2,
        asset_id=77,
        asset_type="resume",
        text=SAMPLE_TEXT,
        version=1,
    )
    assert n > 0
    chunks = fake_store.chunks(collection)
    assert len(chunks) == n
    assert all(rec["metadata"][META_IS_LATEST] is True for rec in chunks.values())
