"""Tests for retrieval.bm25_index — pure logic, no real corpus or files."""

from __future__ import annotations

from retrieval.bm25_index import Bm25Index, _tokenize


def _chunk(chunk_id: str, act_name: str, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "act_name": act_name,
        "act_year": 2015,
        "section_number": "Section 1",
        "section_title": "Test section",
        "page": 1,
        "source_url": "https://example.com/act.pdf",
        "version_date": "2015-01-01",
        "ocr": False,
        "superseded_risk": False,
        "text": text,
    }


def _sample_chunks() -> list[dict]:
    return [
        _chunk(
            "shops__s1",
            "Sindh Shops and Commercial Establishments Act",
            "1. Short title, extent and commencement. This Act may be called the "
            "Sindh Shops and Commercial Establishments Act, 2015.",
        ),
        _chunk(
            "shops__s14",
            "Sindh Shops and Commercial Establishments Act",
            "14. Every employee shall be allowed leave with full wages for a "
            "period of fourteen days after continuous employment for twelve months.",
        ),
        _chunk(
            "standing_orders__s1",
            "Sindh Terms of Employment (Standing Orders) Act",
            "1. Short title, extent and commencement. This Act may be called the "
            "Sindh Terms of Employment (Standing Orders) Act, 2015.",
        ),
    ]


def test_tokenize_lowercases_and_splits_on_non_alphanumeric():
    assert _tokenize("Fourteen Days' Leave, 2015!") == ["fourteen", "days", "leave", "2015"]


def test_specific_term_outranks_boilerplate_short_title_section():
    """The real Milestone 4/5 finding: a query mentioning "Sindh" and the Act
    name matches every act's own short-title section almost as well as the
    genuinely relevant section, unless the specific content terms (here,
    "leave", "fourteen") carry more weight than the ubiquitous ones."""
    index = Bm25Index(_sample_chunks())
    results = index.search("how many days of leave under Sindh law", top_k=3)

    assert results, "expected at least one result"
    top_chunk, _score = results[0]
    assert top_chunk["chunk_id"] == "shops__s14"


def test_act_name_filter_excludes_other_acts():
    index = Bm25Index(_sample_chunks())
    results = index.search("short title", top_k=5, act_name="Sindh Shops and Commercial Establishments Act")

    assert results
    assert all(chunk["act_name"] == "Sindh Shops and Commercial Establishments Act" for chunk, _ in results)


def test_search_respects_top_k():
    index = Bm25Index(_sample_chunks())
    results = index.search("short title act", top_k=1)
    assert len(results) == 1


def test_empty_index_returns_no_results():
    index = Bm25Index([])
    assert index.search("anything", top_k=5) == []
