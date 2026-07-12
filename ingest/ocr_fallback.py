"""OCR fallback for the one document confirmed to be a genuine scanned PDF.

Not a general OCR pipeline — deliberately scoped to the minimum-wage gazette
notification only (see its `notes` field in ingest/sources.py). Adding OCR
support for any other document should be a separate, deliberate decision,
not an automatic fallback, per this project's "never guess, always verify"
rule for ingestion.

Usage: python -m ingest.ocr_fallback
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from ingest.sources import SOURCES

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
INTERIM_DIR = Path(__file__).resolve().parent.parent / "data" / "interim"

OCR_DOC_IDS = {"sindh_minimum_wages_gazette_latest"}
OCR_DPI = 300


def ocr_pdf_pages(pdf_path: Path) -> list[dict]:
    """Rasterize each page and run OCR, returning the same page-record shape
    ingest.parse produces (page_number, text, char_count)."""
    doc = fitz.open(str(pdf_path))
    pages: list[dict] = []
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=OCR_DPI)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(image, lang="eng").strip()
        pages.append({"page_number": i, "text": text, "char_count": len(text)})
    doc.close()
    return pages


def run() -> list[str]:
    """OCR every registered OCR-flagged document with a downloaded PDF.

    Returns the list of doc_ids successfully processed.
    """
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    processed: list[str] = []

    for source in SOURCES:
        if source.doc_id not in OCR_DOC_IDS:
            continue

        pdf_path = RAW_DIR / source.output_filename
        if not pdf_path.exists():
            print(f"SKIPPED: {source.doc_id} — no file at {pdf_path}; run ingest.download first.")
            continue

        pages = ocr_pdf_pages(pdf_path)
        record = {
            "doc_id": source.doc_id,
            "act_name": source.act_name,
            "act_year": source.act_year,
            "source_file": str(pdf_path),
            "source_url": source.url,
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "is_scanned": True,
            "ocr_applied": True,
            "ocr_dpi": OCR_DPI,
            "num_pages": len(pages),
            "pages": pages,
        }
        out_path = INTERIM_DIR / f"{source.doc_id}.json"
        out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"OCR'd {source.doc_id}: {len(pages)} pages -> {out_path}")
        processed.append(source.doc_id)

    return processed


if __name__ == "__main__":
    run()
