"""市场数据检索层测试：公共集合 where 归一化 / market_collection_name / collection 参数。"""

import pytest

from services.rag.clients import market_collection_name
from services.rag.metadata import META_ASSET_ID, META_ASSET_TYPE, META_IS_LATEST
from services.rag.retrieval import build_asset_where, build_scope_where, hybrid_search_corpus
from services.vector_store.chroma_adapter import ChromaAdapter


# ── ChromaAdapter where 归一化（修复多顶层字段 where 报错） ──


def test_normalize_where_multi_field_to_and():
    """多顶层字段 where → 包成 $and（Chroma 只接受单操作符顶层）。"""
    where = {META_ASSET_ID: 289, META_IS_LATEST: True}
    normalized = ChromaAdapter._normalize_where(where)
    assert normalized == {"$and": [{META_ASSET_ID: 289}, {META_IS_LATEST: True}]}


def test_normalize_where_single_field_passthrough():
    """单字段 where 原样透传。"""
    where = {META_IS_LATEST: True}
    assert ChromaAdapter._normalize_where(where) == where


def test_normalize_where_compound_passthrough():
    """已是 $and/$or 复合操作符的原样透传。"""
    where = {"$and": [{META_ASSET_ID: 1}, {META_IS_LATEST: True}]}
    assert ChromaAdapter._normalize_where(where) == where


def test_normalize_where_nested_in_passthrough():
    """单字段 + $in 值原样（嵌套运算符不影响顶层）。"""
    where = {META_ASSET_ID: {"$in": [1, 2, 3]}}
    assert ChromaAdapter._normalize_where(where) == where


def test_normalize_where_empty():
    """空 where 原样返回。"""
    assert ChromaAdapter._normalize_where(None) is None
    assert ChromaAdapter._normalize_where({}) == {}


# ── 公共集合命名 ──


def test_market_collection_name():
    assert market_collection_name() == "market_public"


# ── 检索 where 构造 ──


def test_build_asset_where_job():
    """build_asset_where 按 asset_type 限定 + is_latest。"""
    where = build_asset_where("job")
    assert where == {META_ASSET_TYPE: "job", META_IS_LATEST: True}


def test_build_asset_where_with_ids():
    where = build_asset_where("job", asset_ids=[1, 2])
    assert where[META_IS_LATEST] is True
    assert where[META_ASSET_ID] == {"$in": [1, 2]}


def test_build_scope_where_still_works():
    """既有 scope where 构造行为不变。"""
    where = build_scope_where({"resume": [1, 2]})
    assert where[META_IS_LATEST] is True
    assert where[META_ASSET_ID] == {"$in": [1, 2]}


# ── hybrid_search_corpus collection 参数（mock 内部检索避免真实 Chroma/embedding） ──


@pytest.mark.asyncio
async def test_hybrid_search_corpus_market_collection(monkeypatch):
    """传 collection 参数时，内部检索用公共集合且 BM25 key 带 market 前缀。"""
    from services.rag import retrieval

    captured = {}

    async def fake_vector(collection, where, question, top_k):
        captured["collection"] = collection
        captured["where"] = where
        return []

    async def fake_keyword(collection, where, store_key, question, top_k):
        captured["store_key"] = store_key
        return []

    monkeypatch.setattr(retrieval, "_vector_search", fake_vector)
    monkeypatch.setattr(retrieval, "_keyword_search", fake_keyword)

    result = await hybrid_search_corpus(
        1, {"job": [10]}, "问题", top_k=5, collection="market_public"
    )
    assert result == []
    assert captured["collection"] == "market_public"
    assert captured["store_key"].startswith("market:market_public:")


@pytest.mark.asyncio
async def test_hybrid_search_corpus_default_user_collection(monkeypatch):
    """不传 collection 时保持默认每用户集合 + 原 BM25 key 格式。"""
    from services.rag import retrieval

    captured = {}

    async def fake_vector(collection, where, question, top_k):
        captured["collection"] = collection
        return []

    async def fake_keyword(collection, where, store_key, question, top_k):
        captured["store_key"] = store_key
        return []

    monkeypatch.setattr(retrieval, "_vector_search", fake_vector)
    monkeypatch.setattr(retrieval, "_keyword_search", fake_keyword)

    await hybrid_search_corpus(1, {"resume": [5]}, "问题", top_k=5)
    assert captured["collection"] == "knowledge_1"
    assert captured["store_key"] == "1:[5]"
