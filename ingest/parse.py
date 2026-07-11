"""Parse downloaded PDFs into clean per-page text with page numbers preserved.

Usage: python -m ingest.parse

For every core document that was successfully downloaded, extracts text
page-by-page (pypdf first; pdfplumber as a cross-check on thin pages) and
writes data/interim/<doc_id>.json. Detects likely-scanned documents via a
simple text-density heuristic and surfaces them in a parse report rather than
silently guessing at OCR — per SPEC.md, a flagged document is a decision for
a human, not something this pipeline resolves on its own.

This milestone does not attach legal-section metadata (section_number,
section_title) — that is Milestone 2's job. It only guarantees clean
per-page text with page numbers preserved.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from ingest.sources import DocumentSource, core_sources

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
INTERIM_DIR = Path(__file__).resolve().parent.parent / "data" / "interim"
PARSE_REPORT_PATH = INTERIM_DIR / "parse_report.json"

MIN_CHARS_PER_PAGE = 40
SCANNED_PAGE_FRACTION_THRESHOLD = 0.6


@dataclass
class PageText:
    page_number: int
    text: str
    char_count: int


def is_scanned(pages: list[dict]) -> tuple[bool, float]:
    """Flag a document as likely-scanned based on the fraction of thin pages.

    A page with fewer than MIN_CHARS_PER_PAGE extracted characters is
    considered "thin" (i.e. probably an image with no embedded text layer).
    If enough pages are thin, the whole document is flagged.
    """
    if not pages:
        return True, 1.0
    thin = sum(1 for p in pages if p["char_count"] < MIN_CHARS_PER_PAGE)
    fraction = thin / len(pages)
    return fraction >= SCANNED_PAGE_FRACTION_THRESHOLD, fraction


def extract_pages(pdf_path: Path) -> list[PageText]:
    """Extract per-page text, using pdfplumber to cross-check thin pypdf pages."""
    reader = PdfReader(str(pdf_path))
    pages: list[PageText] = []

    plumber_doc = None
    try:
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()

            if len(text) < MIN_CHARS_PER_PAGE:
                if plumber_doc is None:
                    plumber_doc = pdfplumber.open(str(pdf_path))
                plumber_text = (plumber_doc.pages[i - 1].extract_text() or "").strip()
                if len(plumber_text) > len(text):
                    text = plumber_text

            pages.append(PageText(page_number=i, text=text, char_count=len(text)))
    finally:
        if plumber_doc is not None:
            plumber_doc.close()

    return pages


def parse_document(source: DocumentSource) -> dict | None:
    """Parse one document; return its JSON-serializable record, or None if missing."""
    pdf_path = RAW_DIR / source.output_filename
    if not pdf_path.exists():
        return None

    pages = extract_pages(pdf_path)
    page_dicts = [asdict(p) for p in pages]
    scanned, scanned_fraction = is_scanned(page_dicts)

    return {
        "doc_id": source.doc_id,
        "act_name": source.act_name,
        "act_year": source.act_year,
        "source_file": str(pdf_path),
        "source_url": source.url,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "is_scanned": scanned,
        "scanned_page_fraction": round(scanned_fraction, 3),
        "num_pages": len(page_dicts),
        "pages": page_dicts,
    }


def parse_all() -> tuple[list[dict], list[str]]:
    """Parse every core source that has a downloaded PDF.

    Returns (records, missing_doc_ids) — missing_doc_ids are core documents
    with no file in data/raw/, which is treated as a pipeline precondition
    failure (run ingest.download first), not something to guess around.
    """
    records: list[dict] = []
    missing: list[str] = []

    for source in core_sources():
        record = parse_document(source)
        if record is None:
            missing.append(source.doc_id)
        else:
            records.append(record)

    return records, missing


def _write_outputs(records: list[dict]) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    for record in records:
        out_path = INTERIM_DIR / f"{record['doc_id']}.json"
        out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    report = [
        {
            "doc_id": r["doc_id"],
            "act_name": r["act_name"],
            "num_pages": r["num_pages"],
            "is_scanned": r["is_scanned"],
            "scanned_page_fraction": r["scanned_page_fraction"],
        }
        for r in records
    ]
    PARSE_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _print_report(records: list[dict], missing: list[str]) -> None:
    print(f"{'doc_id':<38} {'pages':<7} {'scanned':<9} fraction")
    print("-" * 70)
    for r in records:
        print(f"{r['doc_id']:<38} {r['num_pages']:<7} {str(r['is_scanned']):<9} {r['scanned_page_fraction']}")

    flagged = [r for r in records if r["is_scanned"]]
    if flagged:
        print()
        for r in flagged:
            print(f"FLAGGED SCANNED: {r['doc_id']} — {r['scanned_page_fraction']:.0%} of pages are text-thin; needs human review (see PROGRESS.md).")

    if missing:
        print()
        for doc_id in missing:
            print(f"ACTION REQUIRED: {doc_id} — no file in data/raw/; run `python -m ingest.download` first.")


def main() -> int:
    records, missing = parse_all()
    _write_outputs(records)
    _print_report(records, missing)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
