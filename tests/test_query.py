"""Tests for retrieval.query — RRF fusion logic and query() wiring.

No real Chroma DB or BM25 corpus involved: _vector_search and _bm25_search
are patched with small, hand-crafted ranked lists so the fusion math and
score convention are verified deterministically.
"""

from __future__ import annotations

from unittest.mock import patch

from retrieval.query import _reciprocal_rank_fusion, query


def _hit(chunk_id: str, act_name: str = "Sindh Test Act", distance: float | None = None) -> tuple[str, dict, str, float | None]:
    metadata = {"act_name": act_name, "act_year": 2015, "section_number": "Section 1",
                "section_title": "Test", "page": 1}
    return (chunk_id, metadata, f"text for {chunk_id}", distance)


def test_rrf_orders_by_fused_score_descending():
    vector_list = [_hit("a"), _hit("b"), _hit("c")]
    bm25_list = [_hit("b"), _hit("a"), _hit("c")]

    fused = _reciprocal_rank_fusion(vector_list, bm25_list)
    ordered_ids = [chunk_id for chunk_id, *_ in fused]

    # "a" and "b" each appear at rank 1 in one list and rank 2 in the other
    # (tied), both ahead of "c" (rank 3 in both).
    assert ordered_ids[2] == "c"
    assert set(ordered_ids[:2]) == {"a", "b"}


def test_rrf_chunk_in_both_lists_outranks_chunk_in_only_one():
    """A chunk ranked #1 in both lists must score higher than a different
    chunk ranked #1 in only one — this is the entire point of fusing two
    independent rankings rather than trusting either alone."""
    vector_list = [_hit("both"), _hit("vector_only")]
    bm25_list = [_hit("both")]

    fused = _reciprocal_rank_fusion(vector_list, bm25_list)
    scores = {chunk_id: score for chunk_id, _, _, _, score in fused}

    assert scores["both"] > scores["vector_only"]


def test_rrf_preserves_metadata_and_text_from_first_list_seen():
    vector_list = [_hit("a", act_name="Act From Vector")]
    bm25_list = [_hit("a", act_name="Act From BM25")]

    fused = _reciprocal_rank_fusion(vector_list, bm25_list)
    chunk_id, metadata, text, distance, _score = fused[0]

    assert metadata["act_name"] == "Act From Vector"


def test_rrf_carries_vector_distance_even_when_bm25_list_seen_first():
    """A chunk found by BM25 (distance=None) and also by vector search
    (a real distance) must end up with that real distance attached,
    regardless of which list's tuple was merged into `lookup` first —
    this is what api.generate's refusal threshold depends on."""
    bm25_list = [_hit("a", distance=None)]
    vector_list = [_hit("a", distance=7.5)]

    fused = _reciprocal_rank_fusion(bm25_list, vector_list)
    _chunk_id, _metadata, _text, distance, _score = fused[0]

    assert distance == 7.5


def test_rrf_bm25_only_chunk_has_no_vector_distance():
    bm25_list = [_hit("bm25_only", distance=None)]

    fused = _reciprocal_rank_fusion(bm25_list, [])
    _chunk_id, _metadata, _text, distance, _score = fused[0]

    assert distance is None


def test_query_uses_negative_rrf_score_lower_is_better_convention():
    with patch("retrieval.query._vector_search", return_value=[_hit("a", distance=5.0)]), \
         patch("retrieval.query._bm25_search", return_value=[_hit("a")]):
        hits = query("any question")

    assert len(hits) == 1
    assert hits[0]["score"] < 0  # negative because a lower score must mean "more relevant"
    assert hits[0]["vector_distance"] == 5.0


def test_query_passes_act_name_filter_to_both_search_backends():
    with patch("retrieval.query._vector_search", return_value=[]) as mock_vector, \
         patch("retrieval.query._bm25_search", return_value=[]) as mock_bm25:
        query("any question", act_name="Sindh Shops and Commercial Establishments Act")

    mock_vector.assert_called_once_with("any question", 20, "Sindh Shops and Commercial Establishments Act")
    mock_bm25.assert_called_once_with("any question", 20, "Sindh Shops and Commercial Establishments Act")


def test_query_respects_top_k():
    vector_list = [_hit("a"), _hit("b"), _hit("c")]
    with patch("retrieval.query._vector_search", return_value=vector_list), \
         patch("retrieval.query._bm25_search", return_value=[]):
        hits = query("any question", top_k=2)

    assert len(hits) == 2
