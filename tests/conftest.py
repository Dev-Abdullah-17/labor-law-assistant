"""Shared pytest fixtures.

Includes a minimal hand-built PDF generator so the real-PDF parse test does
not need a checked-in binary fixture file — the fixture is fully reviewable
as code and generated fresh in a temp directory for each test.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _make_pdf_bytes(page_texts: list[str]) -> bytes:
    """Build a minimal, valid multi-page PDF with real extractable text."""
    catalog_obj_num = 1
    pages_obj_num = 2
    font_obj_num = 3
    num_pages = len(page_texts)

    page_obj_nums = list(range(4, 4 + num_pages))
    content_obj_nums = list(range(4 + num_pages, 4 + 2 * num_pages))

    objects: dict[int, bytes] = {
        catalog_obj_num: f"<< /Type /Catalog /Pages {pages_obj_num} 0 R >>".encode(),
        pages_obj_num: (
            f"<< /Type /Pages /Kids [{' '.join(f'{n} 0 R' for n in page_obj_nums)}] "
            f"/Count {num_pages} >>"
        ).encode(),
        font_obj_num: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    for i, text in enumerate(page_texts):
        page_num = page_obj_nums[i]
        content_num = content_obj_nums[i]
        objects[page_num] = (
            f"<< /Type /Page /Parent {pages_obj_num} 0 R /MediaBox [0 0 300 200] "
            f"/Resources << /Font << /F1 {font_obj_num} 0 R >> >> "
            f"/Contents {content_num} 0 R >>"
        ).encode()
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 12 Tf 10 150 Td ({escaped}) Tj ET".encode()
        objects[content_num] = f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for obj_num in sorted(objects):
        offsets[obj_num] = len(out)
        out += f"{obj_num} 0 obj\n".encode()
        out += objects[obj_num]
        out += b"\nendobj\n"

    xref_offset = len(out)
    max_obj = max(objects)
    out += f"xref\n0 {max_obj + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for obj_num in range(1, max_obj + 1):
        out += f"{offsets.get(obj_num, 0):010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {max_obj + 1} /Root {catalog_obj_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    ).encode()
    return bytes(out)


@pytest.fixture
def sample_pdf_path(tmp_path) -> Path:
    """A small, real, text-native 3-page PDF for parse.py's real-extraction test."""
    path = tmp_path / "sample_text.pdf"
    path.write_bytes(
        _make_pdf_bytes(
            [
                "Section 1. Short title and commencement of this sample Act.",
                "Section 2. Definitions used throughout this sample Act for testing.",
                "Section 3. Miscellaneous provisions concluding the sample Act.",
            ]
        )
    )
    return path


@pytest.fixture
def blank_pdf_path(tmp_path) -> Path:
    """A 2-page PDF with no extractable text, to exercise scanned-detection."""
    path = tmp_path / "blank.pdf"
    path.write_bytes(_make_pdf_bytes(["", ""]))
    return path
