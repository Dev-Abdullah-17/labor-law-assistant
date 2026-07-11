# Progress Log

## Milestone 1 — Project skeleton + document ingestion (2026-07-11)

### Built
- Project skeleton: `ingest/`, `retrieval/`, `api/`, `eval/`, `frontend/`, `data/{raw,interim,processed}/`, `tests/`.
- `ingest/sources.py` — declarative registry of 9 documents (6 core for this milestone, 3 explicitly deferred to Phase 2: Factories Act, EOBI Act, Workers Compensation Act).
- `ingest/download.py` — downloads core documents, classifying each attempt as `SUCCESS` / `FAILED` / `SKIPPED_NO_URL`. Never invents a fallback URL; writes `data/raw/download_manifest.json`; exits non-zero with an `ACTION REQUIRED` line per unresolved document. Idempotent via sha256 check.
- `ingest/parse.py` — extracts per-page text (pypdf primary, pdfplumber cross-check on text-thin pages), writes `data/interim/<doc_id>.json`, and flags likely-scanned documents via a text-density heuristic rather than guessing at OCR.
- 20 pytest tests across `test_sources.py`, `test_download.py` (network fully mocked), `test_parse.py` (uses a hand-built PDF fixture generated in `conftest.py`, not a checked-in binary).

### Documents ingested

| doc_id | status | pages | is_scanned | source |
|---|---|---|---|---|
| sindh_standing_orders_2015 | SUCCESS | 20 | No | sindhlaws.gov.pk (given in SPEC.md) |
| sindh_shops_commercial_2015 | SUCCESS | 19 | No | sindhlaws.gov.pk (found by search, content-verified) |
| sindh_minimum_wages_2015 | SUCCESS | 14 | No | sindhlaws.gov.pk (found by search, content-verified) |
| sindh_minimum_wages_gazette_latest | SUCCESS (download) | 3 | **Yes — 100%** | lhr.sindh.gov.pk (found by search) |
| sindh_payment_of_wages_2015 | SUCCESS | 16 | No | sindhlaws.gov.pk (found by search, content-verified) |
| sindh_industrial_relations_2013 | SUCCESS | 59 | No | sindhhighcourt.gov.pk (given in SPEC.md) |

All 6 core documents downloaded on the first attempt (no retries needed). For the 3 documents whose URLs were not given in SPEC.md (Shops & Commercial Establishments Act, Minimum Wages Act, Payment of Wages Act), the candidate sindhlaws.gov.pk URLs found by search were verified against the extracted first-page text after downloading — each page 1 header matches the expected act name and year exactly (e.g. "SINDH ACT NO.XII OF 2016 THE SINDH SHOPS AND COMMERCIAL ESTABLISHMENT ACT, 2015"). See `ingest/sources.py` `notes` fields for the full provenance trail per document.

### Decisions
- **Added `data/interim/`**, not in SPEC.md's literal folder tree, to hold per-page parsed text (this milestone's output) separately from `data/processed/`, which SPEC.md defines as Milestone 2's *chunked* JSON output — different schema, shouldn't share a directory.
- **Industrial Relations Act**: ingested the 2013 Act only (matches the URL given in SPEC.md; confirmed text-native, sourced from the Sindh High Court). **Resolved (2026-07-11):** the Sindh Industrial Relations Act 2021 document (clr.org.pk) is the **Rules made under the 2013 Act**, not a superseding Act — the 2013 Act remains the current, correct primary source. No further action needed. Closed.
- **Fixture PDFs generated at test time** (`tests/conftest.py`) rather than checked in as static binaries — keeps the whole test suite reviewable as code with no binary diffs in git history.

### What broke / open items
- **Minimum wage gazette notification — still open.** The original download (`sindh_minimum_wages_gazette_latest.pdf`, from lhr.sindh.gov.pk) was a CamScanner scan with no text layer (all 3 pages extracted to just the literal string "CamScanner") and has been **deleted** from `data/raw/` and `data/interim/`. Two replacement candidates were tried on 2026-07-11, verifying content as before rather than trusting the URL blindly:
  - `clr.org.pk/Labour-Laws/Minimum Wage Notification/Sindh Unskilled Workers Minimum Wages 2025.pdf` — resolves (200, real PDF, 3 pages) but is **also scanned/image-only**: 0 extractable characters on every page via both pypdf and pdfplumber.
  - `sessi.gov.pk/Unskilled Minimum Wage 25-26.pdf` — **404, dead link**.

  Neither produced a usable text-native document, so no replacement has been ingested — this act is currently **not represented in the corpus**. Target content once a working source is found: Sindh, FY 2025-26, Rs 40,000/month for unskilled workers, effective 1 July 2025 (`version_date` should be set to `2025-07-01`). Note for whenever this is resolved: **a revised Rs 43,000 notification is reportedly pending (proposed July 2026)** — this document will need updating again once that notification is formally issued. Next step: source a text-native copy manually (a scan is fine as source-of-truth for a human, but not for this pipeline without adding OCR, which is out of scope unless requested).

### Metrics
- 6/6 core documents downloaded successfully on first attempt (Milestone 1 baseline); the gazette notification has since been removed pending a usable source, so 5/6 core documents currently have usable ingested content.
- 128 total pages parsed across the 5 remaining documents (20 + 19 + 14 + 16 + 59).
- 20 pytest tests, all passing; no real network calls in the test suite (requests fully mocked in `test_download.py`).
