from unittest.mock import AsyncMock, patch

import pytest

from services.rag.retrieval import (
    _load_bm25_index,
    _scope_bm25_key,
    _vector_search,
    build_scope_where,
    clear_bm25,
    clear_user_bm25,
)
from services.rag.corpus_retrieval import _rrf_merge_by_asset


def test_empty_scope_only_filters_latest_snapshot():
    assert build_scope_where({}) == {"is_latest": True}


def test_single_asset_type_scope_couples_type_and_ids():
    assert build_scope_where({"resume": [2, 1]}) == {
        "is_latest": True,
        "asset_type": "resume",
        "asset_id": {"$in": [1, 2]},
    }


def test_multi_asset_type_scope_uses_or_without_cross_type_id_leakage():
    assert build_scope_where({"resume": [1, 2], "jd": [9]}) == {
        "$and": [
            {"is_latest": True},
            {
                "$or": [
                    {"$and": [{"asset_type": "jd"}, {"asset_id": 9}]},
                    {"$and": [{"asset_type": "resume"}, {"asset_id": {"$in": [1, 2]}}]},
                ]
            },
        ]
    }


def test_bm25_scope_key_is_stable_and_keeps_asset_type_isolation():
    left = _scope_bm25_key(7, {"resume": [2, 1], "jd": [9]})
    reordered = _scope_bm25_key(7, {"jd": [9], "resume": [1, 2]})
    different_type = _scope_bm25_key(7, {"sample": [1, 2], "jd": [9]})

    assert left == reordered
    assert left != different_type
    assert '"resume":[1,2]' in left


@pytest.mark.asyncio
async def test_clear_bm25_removes_only_matching_asset_type_scope():
    from services.rag import retrieval

    retrieval._bm25_indexes.clear()
    resume_key = _scope_bm25_key(7, {"resume": [3]})
    mixed_key = _scope_bm25_key(7, {"resume": [3], "jd": [3]})
    jd_key = _scope_bm25_key(7, {"jd": [3]})
    retrieval._bm25_indexes[resume_key] = (None, [])
    retrieval._bm25_indexes[mixed_key] = (None, [])
    retrieval._bm25_indexes[jd_key] = (None, [])

    await clear_bm25(7, 3, asset_type="resume")

    assert resume_key not in retrieval._bm25_indexes
    assert mixed_key not in retrieval._bm25_indexes
    assert jd_key in retrieval._bm25_indexes
    retrieval._bm25_indexes.clear()


@pytest.mark.asyncio
async def test_clear_user_bm25_clears_new_and_legacy_user_keys_only():
    from services.rag import retrieval

    retrieval._bm25_indexes.clear()
    retrieval._bm25_indexes[_scope_bm25_key(7, {"resume": [1]})] = (None, [])
    retrieval._bm25_indexes["7:[2]"] = (None, [])
    retrieval._bm25_indexes[_scope_bm25_key(8, {"resume": [1]})] = (None, [])
    retrieval._bm25_indexes["market:public:scope:{}"] = (None, [])

    await clear_user_bm25(7)

    assert not any(key.startswith("user:7:") or key.startswith("7:[") for key in retrieval._bm25_indexes)
    assert _scope_bm25_key(8, {"resume": [1]}) in retrieval._bm25_indexes
    assert "market:public:scope:{}" in retrieval._bm25_indexes
    retrieval._bm25_indexes.clear()


@pytest.mark.asyncio
async def test_dense_retrieval_preserves_complete_metadata():
    item = {
        "text": "agent evidence",
        "score": 0.75,
        "metadata": {
            "asset_type": "resume",
            "asset_id": 3,
            "version": 4,
            "chunk_index": 5,
            "section": "projects",
            "start_char": 10,
            "end_char": 24,
            "custom": "preserved",
        },
    }
    store = AsyncMock()
    store.query.return_value = [item]
    with patch("services.rag.retrieval.get_embeddings", new=AsyncMock(return_value=[[0.1]])), patch(
        "services.rag.retrieval.get_vector_store", return_value=store
    ):
        result = await _vector_search("collection", {"is_latest": True}, "q", 5)

    assert result[0]["start_char"] == 10
    assert result[0]["end_char"] == 24
    assert result[0]["asset_type"] == "resume"
    assert result[0]["custom"] == "preserved"
    assert result[0]["retrieval_source"] == "dense"


@pytest.mark.asyncio
async def test_bm25_index_preserves_complete_metadata():
    store = AsyncMock()
    store.get.return_value = [
        {
            "text": "agent evidence",
            "metadata": {
                "asset_type": "resume",
                "asset_id": 3,
                "version": 4,
                "chunk_index": 5,
                "section": "projects",
                "start_char": 10,
                "end_char": 24,
                "custom": "preserved",
            },
        }
    ]
    with patch("services.rag.retrieval.get_vector_store", return_value=store):
        assert await _load_bm25_index("collection", {"is_latest": True}, "evidence-test")

    from services.rag.retrieval import _bm25_indexes

    chunk = _bm25_indexes["evidence-test"][1][0]
    assert chunk["start_char"] == 10
    assert chunk["asset_type"] == "resume"
    assert chunk["custom"] == "preserved"


def test_corpus_rrf_merge_keeps_same_text_for_different_asset_types():
    dense = [
        {
            "text": "same",
            "asset_type": "interview",
            "asset_id": 4,
            "version": 2,
            "chunk_index": 0,
            "start_char": 1,
            "end_char": 5,
        }
    ]
    sparse = [
        {
            "text": "same",
            "asset_type": "resume_sample",
            "asset_id": 4,
            "version": 2,
            "chunk_index": 0,
            "start_char": 1,
            "end_char": 5,
        }
    ]

    merged = _rrf_merge_by_asset(dense, sparse, top_k=5)

    assert len(merged) == 2
    assert {item["asset_type"] for item in merged} == {"interview", "resume_sample"}
    assert all(item["version"] == 2 for item in merged)
    assert all(item["chunk_index"] == 0 for item in merged)
    assert all(item["start_char"] == 1 and item["end_char"] == 5 for item in merged)
    assert all(item["score_kind"] == "rrf" for item in merged)
    assert {item["retrieval_source"] for item in merged} == {"dense", "sparse"}
