from services.agentic_rag.generate import _extract_sources
from services.agentic_rag.search import _deduplicate_chunks
from services.rag.evidence import (
    ScoreKind,
    evidence_identity,
    evidence_to_public,
    normalize_evidence,
    normalize_evidence_list,
    adapt_evidence,
)
from services.react_agent.loop import _deduplicate_sources
from api.qa import _to_source_item


def test_normalize_canonical_evidence_preserves_provenance():
    evidence = normalize_evidence(
        {
            "text": "Built an agent",
            "asset_type": "resume",
            "asset_id": 7,
            "version": 3,
            "chunk_index": 2,
            "section": "projects",
            "start_char": 10,
            "end_char": 24,
            "score": 0.91,
            "score_kind": "rerank_relevance",
            "retrieval_source": "hybrid",
        }
    )

    assert evidence is not None
    assert evidence.asset_id == 7
    assert evidence.score_kind is ScoreKind.RERANK_RELEVANCE
    assert evidence_to_public(evidence) == {
        "text": "Built an agent",
        "asset_type": "resume",
        "asset_id": 7,
        "version": 3,
        "chunk_index": 2,
        "section": "projects",
        "start_char": 10,
        "end_char": 24,
        "score": 0.91,
        "score_kind": "rerank_relevance",
        "retrieval_source": "hybrid",
    }


def test_normalize_accepts_legacy_aliases_without_inventing_provenance():
    evidence = normalize_evidence(
        {"text": "Python", "chunk_id": 4, "rerank_score": 0.8, "source": "dense"}
    )

    assert evidence is not None
    assert evidence.chunk_index == 4
    assert evidence.score == 0.8
    assert evidence.score_kind is ScoreKind.RERANK_RELEVANCE
    assert evidence.retrieval_source == "dense"
    assert evidence.asset_id is None
    assert evidence.asset_type is None
    assert evidence.version is None
    alias = normalize_evidence({"text": "Python", "chunk_index": 4})
    assert alias is not None
    assert evidence_identity(evidence) == evidence_identity(alias)


def test_normalize_accepts_string_chunk_id_without_faking_chunk_index():
    evidence = normalize_evidence(
        {"text": "UUID chunk", "chunk_id": "550e8400-e29b-41d4-a716-446655440000"}
    )
    assert evidence is not None
    assert evidence.chunk_index is None
    assert evidence.chunk_id == "550e8400-e29b-41d4-a716-446655440000"
    public = adapt_evidence(evidence)
    assert public == {
        "text": "UUID chunk",
        "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
    }


def test_rerank_score_wins_over_upstream_retrieval_score():
    evidence = normalize_evidence(
        {"text": "ranked", "score": 0.2, "rerank_score": 0.87, "source": "dense"}
    )
    assert evidence is not None
    assert evidence.score == 0.87
    assert evidence.score_kind is ScoreKind.RERANK_RELEVANCE


def test_invalid_rerank_score_falls_back_to_valid_upstream_score():
    evidence = normalize_evidence(
        {"text": "fallback", "score": 0.42, "rerank_score": "invalid", "source": "dense"}
    )
    assert evidence is not None
    assert evidence.score == 0.42
    assert evidence.score_kind is ScoreKind.DENSE_SIMILARITY


def test_invalid_optional_fields_fail_soft_but_invalid_text_is_dropped():
    evidence = normalize_evidence(
        {
            "text": "valid",
            "asset_id": "not-an-int",
            "start_char": -1,
            "score": "high",
            "score_kind": "mystery",
        }
    )

    assert evidence is not None
    assert evidence.asset_id is None
    assert evidence.start_char is None
    assert evidence.score is None
    assert evidence.score_kind is ScoreKind.UNKNOWN
    assert normalize_evidence({"text": ""}) is None
    normalized = normalize_evidence_list([{"text": "ok"}, {"text": None}, 123])
    assert [item.text for item in normalized] == ["ok"]


def test_identity_distinguishes_same_text_from_different_assets():
    left = normalize_evidence({"text": "same", "asset_type": "resume", "asset_id": 1})
    right = normalize_evidence({"text": "same", "asset_type": "resume", "asset_id": 2})
    assert left is not None and right is not None
    assert evidence_identity(left) != evidence_identity(right)


def test_partial_provenance_does_not_merge_different_text_chunks():
    sources = [
        {"text": "first", "asset_type": "resume"},
        {"text": "second", "asset_type": "resume"},
    ]
    assert len(_deduplicate_sources(sources)) == 2


def test_agentic_merge_keeps_same_text_for_different_asset_types():
    chunks = [
        {"text": "same", "asset_type": "resume", "asset_id": 1, "version": 1, "chunk_index": 0},
        {"text": "same", "asset_type": "jd", "asset_id": 1, "version": 1, "chunk_index": 0},
    ]
    merged = _deduplicate_chunks(chunks)
    assert len(merged) == 2


def test_agentic_merge_keeps_same_provenance_with_different_offsets():
    chunks = [
        {"text": "same", "asset_type": "resume", "asset_id": 1, "version": 1, "chunk_index": 0, "start_char": 0, "end_char": 4},
        {"text": "same", "asset_type": "resume", "asset_id": 1, "version": 1, "chunk_index": 0, "start_char": 8, "end_char": 12},
    ]
    assert len(_deduplicate_chunks(chunks)) == 2


def test_agentic_and_react_sources_use_canonical_adapter_and_provenance_dedup():
    chunks = [
        {
            "text": "same",
            "asset_type": "resume",
            "asset_id": 1,
            "version": 2,
            "chunk_index": 0,
            "start_char": 4,
            "end_char": 8,
            "rerank_score": 0.9,
        },
        {
            "text": "same",
            "asset_type": "resume",
            "asset_id": 2,
            "version": 1,
            "chunk_index": 0,
            "rerank_score": 0.8,
        },
    ]

    extracted = _extract_sources(chunks)
    assert extracted[0]["start_char"] == 4
    assert extracted[0]["score_kind"] == "rerank_relevance"
    assert len(_deduplicate_sources(extracted)) == 2
    assert len(_deduplicate_sources([extracted[0], dict(extracted[0])])) == 1


def test_api_adapter_keeps_canonical_fields_and_accepts_legacy_history():
    source = _to_source_item(
        {
            "text": "history",
            "chunk_id": 6,
            "asset_type": "resume",
            "asset_id": 8,
            "version": 2,
            "start_char": 3,
            "end_char": 10,
            "score": 0.7,
            "score_kind": "bm25",
            "retrieval_source": "sparse",
        }
    )

    assert source["chunk_index"] == 6
    assert source["asset_id"] == 8
    assert source["version"] == 2
    assert source["score_kind"] == "bm25"
    assert source["retrieval_source"] == "sparse"
    assert _to_source_item("legacy history text") == {"text": "legacy history text"}


def test_api_adapter_preserves_legacy_citation_fields():
    source = _to_source_item(
        {
            "text": "legacy citation",
            "url": "https://example.test/source",
            "title": "Source title",
            "source": "history",
            "rerank_score": 0.8,
        }
    )
    assert source["url"] == "https://example.test/source"
    assert source["title"] == "Source title"
    assert source["source"] == "history"
    assert source["rerank_score"] == 0.8


def test_api_adapter_whitelists_presentation_fields_and_drops_internal_metadata():
    source = _to_source_item(
        {
            "text": "safe",
            "url": "https://example.test/source",
            "title": "Source title",
            "snippet": "short",
            "source": "web",
            "rerank_score": 0.7,
            "chunk_id": "uuid-1",
            "user_id": 99,
            "resume_id": 88,
            "content_hash": "secret",
            "is_latest": True,
        }
    )
    assert source["url"] == "https://example.test/source"
    assert source["chunk_id"] == "uuid-1"
    assert all(key not in source for key in ("user_id", "resume_id", "content_hash", "is_latest"))


def test_react_source_dedup_uses_same_presentation_whitelist():
    sources = _deduplicate_sources(
        [
            {
                "text": "safe",
                "url": "https://example.test/source",
                "title": "Source title",
                "user_id": 99,
                "resume_id": 88,
                "content_hash": "secret",
                "is_latest": True,
            }
        ]
    )
    assert sources[0]["url"] == "https://example.test/source"
    assert sources[0]["title"] == "Source title"
    assert all(key not in sources[0] for key in ("user_id", "resume_id", "content_hash", "is_latest"))
