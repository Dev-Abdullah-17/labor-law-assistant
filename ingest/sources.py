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


SOURCES: list[DocumentSource] = [
    DocumentSource(
        doc_id="sindh_standing_orders_2015",
        act_name="Sindh Terms of Employment (Standing Orders) Act",
        act_year=2015,
        url="https://sindhlaws.gov.pk/setup/publications_SindhCode/PUB-NEW-18-000108.pdf",
        output_filename="sindh_standing_orders_2015.pdf",
        category="core",
        version_date=None,
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
        version_date=None,
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
        version_date=None,
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
        url="https://lhr.sindh.gov.pk/storage/notification/OL8Q4MaVQ18yHrSR6KekiQcOCvNF23dUdSRuOLyG.pdf",
        output_filename="sindh_minimum_wages_gazette_latest.pdf",
        category="core",
        version_date=None,
        notes=(
            "URL not given in SPEC.md; found by searching lhr.sindh.gov.pk. NOT "
            "independently content-verified. Appears likely to be a scanned/image "
            "PDF based on a preliminary fetch attempt — good real test case for the "
            "scanned-detection heuristic in ingest.parse. Whether this is genuinely "
            "the LATEST notification, and its effective date/rate, are unconfirmed — "
            "human review required before treating this as authoritative."
        ),
    ),
    DocumentSource(
        doc_id="sindh_payment_of_wages_2015",
        act_name="Sindh Payment of Wages Act",
        act_year=2015,
        url="https://sindhlaws.gov.pk/setup/publications_SindhCode/PUB-NEW-18-000186.pdf",
        output_filename="sindh_payment_of_wages_2015.pdf",
        category="core",
        version_date=None,
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
        version_date="2013",
        notes=(
            "Given directly in SPEC.md. SPEC.md also asks whether the Sindh "
            "Industrial Relations Act 2021 (clr.org.pk) supersedes this version. "
            "The 2021 PDF appears to be a scanned/image-heavy document and its "
            "text could not be reviewed to confirm a repeal clause, so this "
            "milestone ingests the 2013 Act only. The 2021 version's existence and "
            "unresolved supersession status is an open item — see PROGRESS.md."
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
