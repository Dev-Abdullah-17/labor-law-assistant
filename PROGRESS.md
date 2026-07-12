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

---

## Milestone 2 — Section-aware chunking + vector store (2026-07-12)

### Built
- `ingest/chunk.py` — section-aware chunker. Looks up `section_title` from each document's own table of contents (not the body text — see Decisions) via `parse_toc`, splits body text into sections via `find_section_boundaries`, and splits any section over 1200 words on sub-clause boundaries `(a)`/`(b)`/`(i)`/`(ii)` with 100-word overlap via `split_oversized_section`. Writes `data/processed/<doc_id>.json`.
- `retrieval/embed.py` — shared wrapper around `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`, used by both indexing and querying so vectors are comparable.
- `retrieval/index.py` — `python -m retrieval.index`: embeds every chunk and (re)builds a persistent local ChromaDB collection at `data/chroma/`.
- `retrieval/query.py` — `python -m retrieval.query "<question>"`: CLI printing the top-5 chunks with score + full citation metadata.
- `tests/test_chunk.py` — 7 new tests against a synthetic fixture deliberately modeling the real quirks found below (not an idealized excerpt), including a regression test for the cross-reference false-positive bug.
- `ingest/sources.py` — `version_date` populated for all 5 core docs with real assent/gazette dates found on each document's own page 2 (not guessed): Standing Orders 2016-04-29, Shops & Commercial 2016-04-29, Minimum Wages 2016-04-12, Payment of Wages 2017-03-22, Industrial Relations 2013-04-01.

### Real data quirks found and fixed (this is where most of the milestone's time went)
Section-aware chunking against SPEC.md's naive regex (`^\s*(\d+[A-Z]?)\.\s+`) produced garbage on first pass. Each of the following was found by inspecting actual chunker output against the real documents, not anticipated in advance:

1. **Section titles are reordered by PDF extraction, in 4 of 5 docs.** The sindhlaws.gov.pk-sourced acts place a section's marginal-note title *after* that section's body text in the extracted stream (a column-layout artifact), not before it. Fixed by looking up titles from each document's own table of contents instead of the body text — works uniformly across both this format and the Industrial Relations Act's different (inline-title) layout.
2. **4-digit years were mistaken for section numbers.** A wrapped line starting "2015." (from "...may be called the ... Act, 2015.") matched the naive boundary regex. Fixed by capping section numbers at 1-3 digits (`\d{1,3}[A-Z]?`), which structurally cannot match a 4-digit run due to regex backtracking.
3. **A cross-reference wrongly split into a fake section.** "...could have been recovered by an application under section \n14." (a line-wrap placing a bare reference number at a line start) was mistaken for a new "Section 14". Fixed with a monotonicity filter: real section numbers strictly increase, so an out-of-sequence match is folded back into the preceding section instead of becoming a spurious boundary. Applied separately per namespace, since the Standing Orders Act's Schedule legitimately restarts numbering at 1.
4. **Repeating page headers polluted TOC titles.** The Industrial Relations Act (a court-library compilation) stamps a running header on every page ("J U D G E S  L I B R A R Y - HIGH COURT OF SINDH, KARACHI"); when a TOC entry wrapped across a page break, the header text got swept in as a spurious "continuation line." Fixed by detecting lines that repeat ≥10 times across the document and filtering them as noise before TOC parsing.
5. **The Standing Orders Act renumbers from 1 inside a `SCHEDULE` block** ("STANDING ORDERS", see section 2(1)(k)) — kept in a separate `Schedule Standing Order N` namespace so it never collides with the main `Section N` numbering. The Shops & Commercial Establishments Act and the Industrial Relations Act both also carry an *unlabeled* Schedule (a registration form template, and a "Public Utility Service" list respectively) picked up by the same generic Schedule-detection logic — their items correctly get the explicit `UNKNOWN — not found in TOC` sentinel rather than a guessed title, since the source genuinely has no title for them.
6. **Two sections (15 and 40) are missing from the Industrial Relations Act's own table of contents** — its TOC jumps 14→16 and 39→41. This is a genuine gap in the source document, confirmed by direct inspection, not a chunker bug. Left as `UNKNOWN` rather than guess-extracting from the inline body text, consistent with the project's "never guess" rule; noted here as an open item if a citation for exactly those two sections is ever needed.

### Verification
Chunked section counts were cross-checked against each document's own TOC entry count (accounting for the Schedule/Public-Utility-Service items not listed in any TOC) and matched exactly for all 5 documents:

| doc_id | chunks | UNKNOWN title | notes |
|---|---|---|---|
| sindh_standing_orders_2015 | 37 | 0 | 14 sections + 23 schedule standing orders, TOC-matched exactly |
| sindh_shops_commercial_2015 | 42 | 8 | 34 sections (TOC-matched) + 8 unlabeled registration-form schedule items |
| sindh_minimum_wages_2015 | 21 | 0 | TOC-matched exactly |
| sindh_payment_of_wages_2015 | 29 | 0 | TOC-matched exactly (incl. 1 oversized section split into 2 parts) |
| sindh_industrial_relations_2013 | 91 | 9 | 82 sections (80 TOC-matched + 2 genuine TOC gaps) + 7 Public Utility Service items + 2 oversized splits |
| **Total** | **220** | **17** | |

`python -m retrieval.index`: 220/220 chunks embedded and indexed into `data/chroma/` without error.

`python -m retrieval.query` — all 5 manual test queries returned the correct section as the top or near-top result:
1. *"how many days notice for termination"* → Standing Orders Act, Schedule Standing Order 16 (Termination of employment) — correct, top result.
2. *"what deductions can be made from an employee's wages"* → Payment of Wages Act, Section 9/7/11/12 (all deduction-related sections) — correct, top 5.
3. *"how is the minimum wage board constituted"* → Minimum Wages Act, Section 3 (Constitution of minimum wages board) — correct, top result.
4. *"what are the working hours for a shop"* → Shops & Commercial Establishments Act, Section 7/8 (opening/closing hours, daily/weekly hours) — correct, top 2.
5. *"how are workers classified as permanent probationer or badli"* → Standing Orders Act, Schedule Standing Order 1 (Classification of worker) — correct, top result.

### Decisions
- Embedding model download required disabling HuggingFace's `hf_xet` fast-download backend (`HF_HUB_DISABLE_XET=1`) and restricting `snapshot_download` to `allow_patterns` for only the files actually needed (`model.safetensors`, tokenizer/config JSON) — the repo also ships redundant `pytorch_model.bin`, 8 ONNX variants, OpenVINO files, and a TF `.h5`, none needed for this project, which were causing repeated multi-GB download timeouts on this environment's slow/unreliable connection.
- "Tokens" for the 1200-word oversized-section threshold are approximated as whitespace word count rather than a precise LLM tokenizer, since the embedding model isn't GPT-tokenized anyway — a dependency-free simplification, not expected to materially change chunking behavior.

### What broke / open items
- Sections 15 and 40 of the Industrial Relations Act have no title (genuine TOC gap in the source — see quirk #6 above).
- The 8 Schedule items in the Shops & Commercial Establishments Act and 7 in the Industrial Relations Act's Public Utility Service list have no title (source genuinely has none — see quirk #5).
- Minimum wage gazette notification remains unresolved from Milestone 1 (see above) — still not in the corpus, so queries about the current minimum wage rate will not retrieve it.

### Metrics
- 220 chunks across 5 documents, 17 with the explicit `UNKNOWN` title sentinel (all traced to genuine source-document gaps, not chunker defects).
- 27 pytest tests total (7 new for the chunker), all passing.
- 5/5 manual test queries returned correct top results.
