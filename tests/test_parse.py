"""Tests for ingest.parse."""

from __future__ import annotations

from ingest.parse import (
    MIN_CHARS_PER_PAGE,
    SCANNED_PAGE_FRACTION_THRESHOLD,
    extract_pages,
    is_scanned,
)


def test_is_scanned_pure_function_all_thin_pages():
    pages = [{"char_count": 0}, {"char_count": 5}, {"char_count": 10}]
    scanned, fraction = is_scanned(pages)
    assert scanned is True
    assert fraction == 1.0


def test_is_scanned_pure_function_all_dense_pages():
    pages = [{"char_count": 500}, {"char_count": 800}]
    scanned, fraction = is_scanned(pages)
    assert scanned is False
    assert fraction == 0.0


def test_is_scanned_at_threshold_boundary():
    # 6 of 10 pages thin == exactly the 0.6 threshold -> flagged
    pages = [{"char_count": 0}] * 6 + [{"char_count": 500}] * 4
    scanned, fraction = is_scanned(pages)
    assert fraction == SCANNED_PAGE_FRACTION_THRESHOLD
    assert scanned is True


def test_is_scanned_empty_document():
    scanned, fraction = is_scanned([])
    assert scanned is True
    assert fraction == 1.0


def test_extract_pages_from_real_text_native_pdf(sample_pdf_path):
    pages = extract_pages(sample_pdf_path)

    assert len(pages) == 3
    assert [p.page_number for p in pages] == [1, 2, 3]
    for p in pages:
        assert p.char_count >= MIN_CHARS_PER_PAGE
        assert p.text.strip() != ""
    assert "Short title" in pages[0].text
    assert "Definitions" in pages[1].text
    assert "Miscellaneous" in pages[2].text


def test_extract_pages_from_blank_pdf_yields_thin_pages(blank_pdf_path):
    pages = extract_pages(blank_pdf_path)

    assert len(pages) == 2
    page_dicts = [{"char_count": p.char_count} for p in pages]
    scanned, _ = is_scanned(page_dicts)
    assert scanned is True
