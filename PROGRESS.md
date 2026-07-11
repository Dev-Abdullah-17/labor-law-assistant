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
- **Industrial Relations Act**: ingested the 2013 Act only (matches the URL given in SPEC.md; confirmed text-native, sourced from the Sindh High Court). The Sindh Industrial Relations Act 2021 (clr.org.pk) was located but appears to be a scanned/image-heavy PDF; its text could not be reviewed to confirm whether it supersedes the 2013 Act. **Open item**: confirm the 2021 Act's status and, if it supersedes the 2013 Act, re-ingest it (likely requiring OCR, since it's scanned) before this act is used in the final knowledge base.
- **Fixture PDFs generated at test time** (`tests/conftest.py`) rather than checked in as static binaries — keeps the whole test suite reviewable as code with no binary diffs in git history.

### What broke / open items
- **`sindh_minimum_wages_gazette_latest.pdf` is a CamScanner scan with no text layer** (all 3 pages extract to just the literal string "CamScanner" — confirmed by inspection). This is a real scanned-document case, not a parsing bug. Per SPEC.md, the ILO NATLEX fallback strategy doesn't apply here (there is no NATLEX alternative for a gazette notification). **This document needs OCR or a text-native replacement before it can be used** — flagging for a decision rather than attempting OCR unprompted. Its "latest" status and the actual wage rate/effective date are also unconfirmed and should be verified against an official source before this feeds any answer.
- Sindh Industrial Relations Act 2021 vs. 2013 — see Decisions above.

### Metrics
- 6/6 core documents downloaded successfully on first attempt.
- 131 total pages parsed across 6 documents (20 + 19 + 14 + 3 + 16 + 59).
- 1/6 documents flagged as scanned (the minimum-wage gazette, 100% of its 3 pages text-thin); 5/6 text-native with 0% thin pages.
- 20 pytest tests, all passing; no real network calls in the test suite (requests fully mocked in `test_download.py`).
