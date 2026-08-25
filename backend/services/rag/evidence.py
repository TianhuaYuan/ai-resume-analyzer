"""Canonical evidence contract shared by RAG, Agentic RAG, and ReAct.

Normalization is deliberately fail-soft for optional metadata: a malformed score or
offset must never discard otherwise usable evidence, and missing provenance is never
filled with guessed values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ScoreKind(str, Enum):
    DENSE_SIMILARITY = "dense_similarity"
    BM25 = "bm25"
    RERANK_RELEVANCE = "rerank_relevance"
    RRF = "rrf"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Evidence:
    text: str
    asset_type: str | None = None
    asset_id: int | None = None
    version: int | None = None
    chunk_index: int | None = None
    chunk_id: str | int | None = None
    section: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    score: float | None = None
    score_kind: ScoreKind | None = None
    retrieval_source: str | None = None


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _optional_int(value: Any, *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def _optional_chunk_id(value: Any) -> str | int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    value = value.strip()
    return value or None


def _optional_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _score_kind(raw: Mapping[str, Any], score: float | None) -> ScoreKind | None:
    value = raw.get("score_kind")
    if value is not None:
        try:
            return ScoreKind(value)
        except (TypeError, ValueError):
            return ScoreKind.UNKNOWN
    if _optional_score(raw.get("rerank_score")) is not None and score is not None:
        return ScoreKind.RERANK_RELEVANCE
    if score is not None:
        source = raw.get("retrieval_source") or raw.get("source")
        if source == "dense":
            return ScoreKind.DENSE_SIMILARITY
        if source == "sparse":
            return ScoreKind.BM25
        if source == "rrf":
            return ScoreKind.RRF
        return ScoreKind.UNKNOWN
    return None


def normalize_evidence(raw: Any) -> Evidence | None:
    """Normalize a dict-like source. Invalid required text drops the item."""
    if isinstance(raw, Evidence):
        return raw
    if isinstance(raw, str):
        text = _optional_string(raw)
        return Evidence(text=text) if text is not None else None
    if not isinstance(raw, Mapping):
        return None
    text = _optional_string(raw.get("text"))
    if text is None:
        return None

    rerank_score = _optional_score(raw.get("rerank_score"))
    upstream_score = _optional_score(raw.get("score"))
    score = rerank_score if rerank_score is not None else upstream_score
    chunk_value = raw.get("chunk_index")
    raw_chunk_id = _optional_chunk_id(raw.get("chunk_id"))
    if chunk_value is None and isinstance(raw_chunk_id, int):
        chunk_value = raw_chunk_id

    return Evidence(
        text=text,
        asset_type=_optional_string(raw.get("asset_type")),
        asset_id=_optional_int(raw.get("asset_id")),
        version=_optional_int(raw.get("version")),
        chunk_index=_optional_int(chunk_value),
        # Integer ``chunk_id`` is legacy alias for chunk_index; keep only
        # opaque string/UUID ids as independent provenance.
        chunk_id=raw_chunk_id if isinstance(raw_chunk_id, str) else None,
        section=_optional_string(raw.get("section")),
        start_char=_optional_int(raw.get("start_char")),
        end_char=_optional_int(raw.get("end_char")),
        score=score,
        score_kind=_score_kind(raw, score),
        retrieval_source=_optional_string(raw.get("retrieval_source") or raw.get("source")),
    )


def normalize_evidence_list(items: Any) -> list[Evidence]:
    if not isinstance(items, (list, tuple)):
        return []
    normalized: list[Evidence] = []
    for item in items:
        evidence = normalize_evidence(item)
        if evidence is not None:
            normalized.append(evidence)
    return normalized


def evidence_identity(evidence: Evidence) -> tuple[Any, ...]:
    """Prefer real provenance; fall back to text only when none exists."""
    provenance = (
        evidence.asset_type,
        evidence.asset_id,
        evidence.version,
        evidence.chunk_index,
        evidence.chunk_id,
        evidence.start_char,
        evidence.end_char,
    )
    if any(value is not None for value in provenance):
        # Text closes gaps in partial provenance (for example asset_type without
        # asset_id/chunk_index) so unrelated chunks cannot collapse together.
        return ("provenance", *provenance, evidence.text)
    return ("text", evidence.text)


def evidence_to_public(evidence: Evidence) -> dict[str, Any]:
    """Return additive canonical API fields, omitting unavailable provenance."""
    values: dict[str, Any] = {
        "text": evidence.text,
        "asset_type": evidence.asset_type,
        "asset_id": evidence.asset_id,
        "version": evidence.version,
        "chunk_index": evidence.chunk_index,
        "chunk_id": evidence.chunk_id,
        "section": evidence.section,
        "start_char": evidence.start_char,
        "end_char": evidence.end_char,
        "score": evidence.score,
        "score_kind": evidence.score_kind.value if evidence.score_kind is not None else None,
        "retrieval_source": evidence.retrieval_source,
    }
    return {key: value for key, value in values.items() if value is not None}


def adapt_evidence(raw: Any, *, preserve_extra: bool = False) -> dict[str, Any] | None:
    """Normalize directly to the public representation.

    ``preserve_extra`` keeps a small allow-list of presentation compatibility
    fields (for example a web citation URL); internal metadata is never copied.
    """
    evidence = normalize_evidence(raw)
    if evidence is None:
        return None
    canonical = evidence_to_public(evidence)
    if preserve_extra and isinstance(raw, Mapping):
        presentation_keys = {
            "url",
            "title",
            "snippet",
            "source",
            "rerank_score",
            "chunk_id",
        }
        extras = {key: raw[key] for key in presentation_keys if key in raw}
        return {**extras, **canonical}
    return canonical


def adapt_evidence_list(items: Any, *, preserve_extra: bool = False) -> list[dict[str, Any]]:
    if not isinstance(items, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        public = adapt_evidence(item, preserve_extra=preserve_extra)
        if public is not None:
            result.append(public)
    return result
