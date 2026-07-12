"""Tests for ingest.chunk.

The synthetic fixture below is not a simplified/idealized excerpt — it
deliberately reproduces the real quirks found in the actual source PDFs
(see ingest/chunk.py's module docstring and PROGRESS.md):
  - a section's marginal-note title is extracted *after* its body text,
    not before it (a PDF column-layout artifact);
  - a SCHEDULE block restarts numbering from 1;
  - a cross-reference like "...under section 1." can land a bare number
    at the start of a wrapped line, which must not be mistaken for a new
    section boundary.
"""

from __future__ import annotations

import re

from ingest.chunk import (
    MAX_SECTION_WORDS,
    OVERLAP_WORDS,
    UNKNOWN_TITLE,
    chunk_document,
    find_section_boundaries,
    parse_toc,
    split_oversized_section,
)

REQUIRED_METADATA_FIELDS = {
    "chunk_id",
    "act_name",
    "act_year",
    "section_number",
    "section_title",
    "page",
    "source_url",
    "version_date",
    "text",
}


def _oversized_clause_body(num_clauses: int = 16, words_per_clause: int = 90) -> str:
    letters = "abcdefghijklmnopqrstuvwxyz"
    clauses = []
    for i in range(num_clauses):
        letter = letters[i] if i < len(letters) else f"z{i}"
        filler = " ".join(f"word{j}" for j in range(words_per_clause))
        clauses.append(f" ({letter}) {filler}.")
    return "\n".join(clauses)


def _sample_pages() -> list[dict]:
    oversized_body = _oversized_clause_body()

    page1 = (
        "SAMPLE ACT NO. I OF 2020\n\n"
        "THE SAMPLE TEST ACT, 2020.\n\n"
        "CONTENTS\n\n"
        "Preamble\n"
        "Sections\n\n"
        "1. Short title, extent and commencement.\n"
        "2. Definitions and interpretation of terms used\n"
        " throughout this Act.\n"
        "3. Oversized obligations of employers under this\n"
        " Act.\n\n"
        "SCHEDULE\n"
        "SAMPLE SCHEDULE\n"
        "( see section 2(1)(a))\n\n"
        "1. First schedule item title.\n"
        "2. Second schedule item title.\n"
    )

    page2 = (
        "[1st January, 2020]\n\n"
        "WHEREAS it is expedient to regulate sample matters;\n\n"
        "It is hereby enacted as follows:-\n\n"
        "Preamble.\n\n"
        "1. (1) This Act may be called the Sample Test Act, 2020.\n\n"
        " (2) It shall come into force at once.\n\n"
        "Short title, extent\n"
        "and commencement.\n\n"
        "2. (1) In this Act, unless there is anything repugnant in the subject\n"
        "or context-\n\n"
        ' (a) "worker" means any person under section 1.\n\n'
        "Definitions and interpretation\n"
        "of terms used throughout\n"
        "this Act.\n\n"
        f"3. (1) An employer shall comply with the following obligations:\n{oversized_body}\n\n"
        "Oversized obligations\n"
        "of employers under this\n"
        "Act.\n"
    )

    page3 = (
        "SCHEDULE\n"
        "SAMPLE SCHEDULE\n"
        "( see section 2(1)(a))\n\n"
        "1. (a) First schedule item body text goes here for testing purposes.\n\n"
        "First schedule item\n"
        "title.\n\n"
        "2. (a) Second schedule item body text, referencing an application under section\n"
        "1.\n\n"
        "Second schedule item\n"
        "title.\n"
    )

    return [
        {"page_number": 1, "text": page1, "char_count": len(page1)},
        {"page_number": 2, "text": page2, "char_count": len(page2)},
        {"page_number": 3, "text": page3, "char_count": len(page3)},
    ]


def _sample_parsed_doc() -> dict:
    return {
        "doc_id": "sample_test_act_2020",
        "act_name": "The Sample Test Act",
        "act_year": 2020,
        "source_url": "https://example.com/sample-test-act.pdf",
        "version_date": "2020-01-01",
        "pages": _sample_pages(),
    }


def test_toc_recovers_titles_despite_body_reordering():
    main_titles, schedule_titles = parse_toc(_sample_pages())

    assert main_titles["1"] == "Short title, extent and commencement."
    assert main_titles["2"] == "Definitions and interpretation of terms used throughout this Act."
    assert main_titles["3"] == "Oversized obligations of employers under this Act."
    assert schedule_titles["1"] == "First schedule item title."
    assert schedule_titles["2"] == "Second schedule item title."


def test_section_boundaries_do_not_split_mid_sentence():
    sections = find_section_boundaries(_sample_pages())
    main_sections = {s.number: s for s in sections if s.namespace == "Section"}

    # Section 1's full text (both subsections) must stay intact, uncut.
    assert "(1) This Act may be called" in main_sections["1"].text
    assert "(2) It shall come into force at once." in main_sections["1"].text
    # It must not have absorbed section 2's body.
    assert "In this Act, unless there is anything repugnant" not in main_sections["1"].text


def test_cross_reference_number_is_not_mistaken_for_a_new_section():
    """'...under section 1.' wraps a bare '1.' to a new line inside schedule
    item 2's body — this must not be split into a spurious extra 'item 1'."""
    sections = find_section_boundaries(_sample_pages())
    schedule_sections = [s for s in sections if s.namespace == "Schedule Standing Order"]

    numbers = [s.number for s in schedule_sections]
    assert numbers == ["1", "2"], f"expected exactly items 1 and 2, got {numbers}"
    assert "referencing an application under section" in schedule_sections[1].text


def test_schedule_numbering_does_not_collide_with_main_numbering():
    chunks = chunk_document(_sample_parsed_doc())
    section_numbers = {c["section_number"] for c in chunks}

    assert "Section 1" in section_numbers
    assert "Schedule Standing Order 1" in section_numbers

    main_1 = next(c for c in chunks if c["section_number"] == "Section 1")
    schedule_1 = next(c for c in chunks if c["section_number"] == "Schedule Standing Order 1")
    assert main_1["section_title"] == "Short title, extent and commencement."
    assert schedule_1["section_title"] == "First schedule item title."


def test_oversized_section_splits_on_subclause_boundaries_with_overlap():
    sections = find_section_boundaries(_sample_pages())
    oversized = next(s for s in sections if s.namespace == "Section" and s.number == "3")
    assert len(oversized.text.split()) > MAX_SECTION_WORDS

    pieces = split_oversized_section(oversized.text)
    assert len(pieces) > 1

    for piece in pieces:
        assert len(piece.split()) <= MAX_SECTION_WORDS + OVERLAP_WORDS

    # Never split mid-clause: every sub-clause in the original section must
    # appear whole (as an uninterrupted substring) in at least one piece.
    # (Pieces after the first legitimately *start* with a word-level overlap
    # fragment of the previous piece's tail, by design — that's not a clause
    # split, so this checks clause wholeness directly rather than piece
    # start-of-string.)
    clause_re = re.compile(r"\([a-z]\) .*?\.(?=\s*\([a-z]\)|\s*$)", re.DOTALL)
    original_clauses = clause_re.findall(oversized.text)
    assert len(original_clauses) >= 10
    combined = "\n".join(pieces)
    for clause in original_clauses:
        assert clause in combined, f"clause was split or lost: {clause[:60]!r}..."

    # Overlap: the tail of piece N should reappear at the head of piece N+1.
    first_tail_words = pieces[0].split()[-10:]
    second_head_words = pieces[1].split()[:10]
    assert set(first_tail_words) & set(second_head_words)


def test_every_chunk_has_full_required_metadata():
    chunks = chunk_document(_sample_parsed_doc())
    assert chunks, "expected at least one chunk"

    for chunk in chunks:
        assert REQUIRED_METADATA_FIELDS.issubset(chunk.keys())
        assert chunk["act_name"] == "The Sample Test Act"
        assert chunk["act_year"] == 2020
        assert chunk["source_url"] is not None
        assert chunk["version_date"] is not None
        assert chunk["page"] is not None
        assert chunk["text"].strip() != ""
        # Title must be either a real string or the explicit sentinel — never
        # a silent None.
        assert chunk["section_title"] is not None
        if chunk["section_title"] == UNKNOWN_TITLE:
            continue
        assert chunk["section_title"].strip() != ""


def test_unknown_title_sentinel_used_when_toc_has_no_entry():
    """A section number with no TOC match gets the explicit UNKNOWN sentinel,
    never a silently missing/omitted title."""
    pages = _sample_pages()
    # Remove section 2's TOC entry to simulate a real gap (as found for
    # sections 15 and 40 in the actual Industrial Relations Act TOC).
    pages[0]["text"] = pages[0]["text"].replace(
        "2. Definitions and interpretation of terms used\n throughout this Act.\n", ""
    )
    doc = {
        "doc_id": "sample_test_act_2020",
        "act_name": "The Sample Test Act",
        "act_year": 2020,
        "source_url": "https://example.com/sample-test-act.pdf",
        "version_date": "2020-01-01",
        "pages": pages,
    }
    chunks = chunk_document(doc)
    section_2 = next(c for c in chunks if c["section_number"] == "Section 2")
    assert section_2["section_title"] == UNKNOWN_TITLE
