"""Declarative registry of source documents for ingestion.

This module is the single source of truth for what documents the pipeline
downloads and parses. It contains no download or parsing logic — only data
and light validation helpers. URLs are never invented: if a document's URL
is unknown or unconfirmed, it is recorded honestly (``url=None`` or a
``notes`` caveat) rather than guessed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentSource:
    """A single document to be downloaded and parsed."""

    doc_id: str
    act_name: str
    act_year: int
    url: str | None
    output_filename: str
    category: str  # "core" | "phase2_skip"
    version_date: str | None
    notes: str
    ocr: bool = False
    superseded_risk: bool = False


SOURCES: list[DocumentSource] = [
    DocumentSource(
        doc_id="sindh_standing_orders_2015",
        act_name="Sindh Terms of Employment (Standing Orders) Act",
        act_year=2015,
        url="https://sindhlaws.gov.pk/setup/publications_SindhCode/PUB-NEW-18-000108.pdf",
        output_filename="sindh_standing_orders_2015.pdf",
        category="core",
        version_date="2016-04-29",
        notes=(
            "Primary source from sindhlaws.gov.pk, given in SPEC.md. Confirmed via "
            "HTTP fetch to be a live 20-page PDF; title text could not be decoded "
            "to independently confirm the act name/year — verify on first read. "
            "The ILO NATLEX fallback (PAK102140.pdf) also listed in SPEC.md returns "
            "HTTP 403 to automated requests and is not usable by download.py; it is "
            "browser-only."
        ),
    ),
    DocumentSource(
        doc_id="sindh_shops_commercial_2015",
        act_name="Sindh Shops and Commercial Establishments Act",
        act_year=2015,
        url="https://sindhlaws.gov.pk/setup/publications_SindhCode/PUB-NEW-18-000109.pdf",
        output_filename="sindh_shops_commercial_2015.pdf",
        category="core",
        version_date="2016-04-29",
        notes=(
            "URL not given in SPEC.md; found by searching sindhlaws.gov.pk. NOT "
            "independently content-verified — confirm this is the correct act on "
            "first read, per CLAUDE.md's 'never guess' rule."
        ),
    ),
    DocumentSource(
        doc_id="sindh_minimum_wages_2015",
        act_name="Sindh Minimum Wages Act",
        act_year=2015,
        url="https://sindhlaws.gov.pk/setup/publications_SindhCode/PUB-NEW-18-000105.pdf",
        output_filename="sindh_minimum_wages_2015.pdf",
        category="core",
        version_date="2016-04-12",
        notes=(
            "URL not given in SPEC.md; found by searching sindhlaws.gov.pk. NOT "
            "independently content-verified — confirm this is the correct act on "
            "first read."
        ),
    ),
    DocumentSource(
        doc_id="sindh_minimum_wages_gazette_latest",
        act_name="Sindh Minimum Wages — Gazette Notification",
        act_year=2015,
        url="https://clr.org.pk/Labour-Laws/Minimum%20Wage%20Notification/Sindh%20Unskilled%20Workers%20Minimum%20Wages%202025.pdf",
        output_filename="sindh_minimum_wages_gazette_latest.pdf",
        category="core",
        version_date="2025-07-01",
        ocr=True,
        superseded_risk=True,
        notes=(
            "RESOLVED (2026-07-12) via approved one-off OCR: this document is a "
            "genuine scanned image PDF (confirmed by pypdf + pdfplumber returning 0 "
            "extractable chars on every page). Two prior candidates also failed — "
            "lhr.sindh.gov.pk (CamScanner scan, deleted) and sessi.gov.pk (404). "
            "OCR'd via ingest.ocr_fallback (PyMuPDF rasterize at 300 DPI + "
            "pytesseract) and manually verified against the extracted text before "
            "indexing: Rs 40,000/month for unskilled adult and adolescent workers, "
            "effective 1 July 2025 (01.07.2025), Government of Sindh Notification "
            "No. L-II-13-3/2016-I dated 28 July 2025, signed by Secretary Muhammad "
            "Rafique Qureshi. Peripheral cc-distribution text on page 3 has minor "
            "OCR noise (garbled names) but the rate/date/authority — the content "
            "that matters for citation — extracted cleanly and consistently across "
            "multiple repeated mentions in the document. "
            "ocr=True and superseded_risk=True are carried through to every chunk's "
            "metadata: a revised Rs 43,000 notification is reportedly pending "
            "(proposed July 2026), so answers citing this document should carry a "
            "'rates may have been revised, verify the latest notification' caveat "
            "(added in Milestone 3's answer generation) until that notification is "
            "formally issued and this document is updated."
        ),
    ),
    DocumentSource(
        doc_id="sindh_payment_of_wages_2015",
        act_name="Sindh Payment of Wages Act",
        act_year=2015,
        url="https://sindhlaws.gov.pk/setup/publications_SindhCode/PUB-NEW-18-000186.pdf",
        output_filename="sindh_payment_of_wages_2015.pdf",
        category="core",
        version_date="2017-03-22",
        notes=(
            "URL not given in SPEC.md; found by searching sindhlaws.gov.pk. NOT "
            "independently content-verified — confirm this is the correct act on "
            "first read."
        ),
    ),
    DocumentSource(
        doc_id="sindh_industrial_relations_2013",
        act_name="Sindh Industrial Relations Act",
        act_year=2013,
        url="https://sindhhighcourt.gov.pk/downloads/source_files/Sindh%20Industrial%20Relation%20Act,%202013.pdf",
        output_filename="sindh_industrial_relations_2013.pdf",
        category="core",
        version_date="2013-04-01",
        notes=(
            "Given directly in SPEC.md. SPEC.md also asks whether the Sindh "
            "Industrial Relations Act 2021 (clr.org.pk) supersedes this version. "
            "Resolved: the 2021 clr.org.pk document is the Rules made under the "
            "2013 Act, not a superseding Act — the 2013 Act remains current and is "
            "the correct primary source. No further action needed; closed in "
            "PROGRESS.md."
        ),
    ),
    DocumentSource(
        doc_id="sindh_maternity_benefits_2018",
        act_name="Sindh Maternity Benefits Act",
        act_year=2018,
        url="https://clr.org.pk/Labour-Laws/Sindh/Sindh%20Maternity%20Benefits%20Act,%202018.pdf",
        output_filename="sindh_maternity_benefits_2018.pdf",
        category="core",
        version_date="2018-05-08",
        notes=(
            "Added (2026-07-12) to close the maternity-leave corpus gap flagged "
            "during Milestone 3 verification — the 1958 Ordinance cross-reference "
            "was superseded for Sindh by this Act (Sindh Act No. XXXIX of 2018). "
            "Two candidate URLs were given for verification: (a) clr.org.pk and "
            "(b) sindhlaws.gov.pk PUB-18-000045. Candidate (a) was downloaded and "
            "inspected directly (pypdf, then deleted the scratch copy) BEFORE "
            "registering this entry: confirmed correct act name/number, 14 "
            "sections, real extractable text (2391 + 2919 chars across 2 pages, "
            "not scanned — no OCR needed), and Section 3 confirms the expected "
            "16-week leave period (4 weeks pre-delivery + 12 weeks post-delivery). "
            "Candidate (b) was not needed. Also a real chunker quirk: unlike 5 of "
            "the other 6 core documents, this Act's PDF has no table of contents "
            "at all — section titles appear inline instead (e.g. '3. Mandatory "
            "maternal leave:'). Handled via a narrowly-scoped inline-title "
            "fallback in ingest/chunk.py (_extract_inline_title), which only "
            "activates when the document's TOC dict is completely empty, so it "
            "cannot mask genuine TOC gaps in other documents (e.g. IRA 2013's "
            "sections 15/40, which correctly remain UNKNOWN_TITLE)."
        ),
    ),
    # Phase 2 — explicitly deferred per SPEC.md. Registered now so the source
    # list is the single place to extend later; not attempted this milestone.
    DocumentSource(
        doc_id="sindh_factories_2015",
        act_name="Sindh Factories Act",
        act_year=2015,
        url=None,
        output_filename="sindh_factories_2015.pdf",
        category="phase2_skip",
        version_date=None,
        notes="Explicitly deferred to Phase 2 per SPEC.md.",
    ),
    DocumentSource(
        doc_id="sindh_eobi_2014",
        act_name="Sindh Employees Old-Age Benefits Act",
        act_year=2014,
        url=None,
        output_filename="sindh_eobi_2014.pdf",
        category="phase2_skip",
        version_date=None,
        notes="Explicitly deferred to Phase 2 per SPEC.md.",
    ),
    DocumentSource(
        doc_id="sindh_workers_compensation_2015",
        act_name="Sindh Workers Compensation Act",
        act_year=2015,
        url=None,
        output_filename="sindh_workers_compensation_2015.pdf",
        category="phase2_skip",
        version_date=None,
        notes="Explicitly deferred to Phase 2 per SPEC.md.",
    ),
]


def core_sources() -> list[DocumentSource]:
    """Return the documents this milestone must attempt to download and parse."""
    return [s for s in SOURCES if s.category == "core"]
