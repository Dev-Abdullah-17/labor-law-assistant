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
- **Minimum wage gazette notification — resolved 2026-07-12 via OCR, see Milestone 2 addendum below.** (Originally: the lhr.sindh.gov.pk and sessi.gov.pk candidates both failed — CamScanner scan with no text layer, and a 404, respectively. Root document is the clr.org.pk scan, which is also image-only. This is a one-off, explicitly-approved scope expansion — not a general OCR capability.)

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
- ~~Minimum wage gazette notification remains unresolved~~ — **resolved 2026-07-12, see addendum below.**

### Metrics
- 220 chunks across 5 documents, 17 with the explicit `UNKNOWN` title sentinel (all traced to genuine source-document gaps, not chunker defects).
- 27 pytest tests total (7 new for the chunker), all passing.
- 5/5 manual test queries returned correct top results.

---

## Addendum to Milestone 2 — Minimum wage gazette resolved via OCR (2026-07-12)

**Approved scope expansion**: OCR for this one document only, not a general capability. Re-downloaded the clr.org.pk scan (`sindh_minimum_wages_gazette_latest.pdf`, 3 pages, confirmed 0 extractable characters via pypdf/pdfplumber — genuinely image-only) and OCR'd it with a new `ingest/ocr_fallback.py` module (PyMuPDF rasterizes each page at 300 DPI, `pytesseract` extracts text; Tesseract 5.4.0 installed via winget).

**Content verified before indexing** (full extracted text reviewed): Rs. 40,000/month for unskilled adult and adolescent workers, effective 1 July 2025 (01.07.2025), Government of Sindh Notification No. L-II-13-3/2016-I dated 28 July 2025, signed by Secretary Muhammad Rafique Qureshi. The rate and date appear consistently across 4+ and 3+ separate mentions respectively — high confidence despite some OCR noise in the peripheral cc-distribution list on page 3 (garbled proper nouns, not load-bearing).

**New metadata fields** — `ocr: bool` and `superseded_risk: bool` added to `DocumentSource` (`ingest/sources.py`) and threaded through every chunk's metadata (`ingest/chunk.py`, `retrieval/index.py`). Both are `True` only for this document; `False` (default) for all others. `superseded_risk` exists because a revised Rs 43,000 notification is reportedly pending (proposed July 2026) — Milestone 3's answer generation should check this flag and append a "rates may have been revised, verify the latest notification" caveat when citing this chunk.

**Chunking design decision**: this document is a gazette notification, not an Act — it has no "enacted as follows" clause, no table of contents, and its numbered items are conditions in an announcement, not statute sections. Forcing it through the Act-oriented section-boundary/TOC pipeline (built for the other 5 documents) would have misapplied "Section N" labels to content that isn't a section of anything. Added a `_chunk_as_whole_document` path in `ingest/chunk.py`, triggered when no enactment clause is found: the whole document becomes one chunk (`section_number: "Notification"`), splitting only if it exceeds the 1200-word threshold (it doesn't — 789 words).

**Verification**: `python -m retrieval.query "what is the current minimum wage for unskilled workers"` returns the gazette chunk as the #2 result (score 7.53) with the correct Rs. 40,000 content, alongside the Minimum Wages Act's board-composition/rate-declaration sections.

### Metrics (updated)
- 221 chunks total (220 + 1 gazette), all 6 core documents now represented in the corpus.
- 28 pytest tests total (1 new for the whole-document chunking path), all passing.

---

## Milestone 3 — Answer generation with citations + chat API/UI (2026-07-12)

### Built
- `api/generate.py` — `generate_answer(question, hits)`: two-layer refusal (score-threshold pre-filter, no LLM call if the best retrieval score exceeds 12.0; an LLM-level instruction to refuse if the retrieved excerpts don't actually answer the question even after passing the score filter). Cites as `(Act Name Year, s. N, p. P)`. Appends a fixed caveat sentence when any cited chunk has `superseded_risk: True`.
- `api/rewrite.py` — `rewrite_query(question, history)`: skips the LLM call entirely for single-turn conversations (no history); otherwise rewrites a follow-up into a standalone question.
- `api/main.py` — FastAPI app: `POST /chat` (rewrite → retrieve → generate pipeline), `GET /health` (verifies the Chroma collection is reachable, returns chunk count or 503).
- `frontend/index.html` — single-file vanilla JS/HTML/CSS chat UI: scope disclaimer banner, chat bubbles, refused-answer styling, expandable citation cards showing the actual chunk text. No build step, no framework.
- `tests/test_generate.py`, `tests/test_rewrite.py` — 9 new tests, LLM client fully mocked, no real network calls.

### The provider story — three attempts before something worked
This milestone's biggest time sink wasn't the RAG logic — it was finding an LLM provider the user could actually use for free. Recorded in detail because it's a real part of the build, not a footnote:

1. **Anthropic** (`claude-sonnet-5` + `claude-haiku-4-5`) — the original plan, fully implemented and working (structurally verified via mocked tests and live request wiring). Abandoned per explicit user request for a genuinely free option — Anthropic requires a card on file.
2. **Google Gemini free tier** (`gemini-3.5-flash` + `gemini-3.1-flash-lite`) — rewritten to use `google-genai`. First hit a 403 on the newer `client.interactions.create()` API surface; switched to the older, universally-available `client.models.generate_content()` — same 403. Isolated with a minimal repro (`client.models.list()` succeeds, every `generate_content()` call fails identically across 3 different models) to confirm it wasn't a code or model-name issue. Root cause, confirmed by the user's AI Studio dashboard screenshot: **both of their Gemini API keys show "Set up billing — Unavailable"** — Google's "free tier" still gates the generation endpoint behind a linked billing account (listing models doesn't require it, generating does), even though free-tier usage itself isn't billed. Not genuinely cardless.
3. **Groq free tier** (`openai/gpt-oss-120b` + `llama-3.1-8b-instant`) — genuinely no card required (confirmed by direct research before implementing, not assumed). Works immediately once a key was created at console.groq.com. This is what shipped.

Also caught and fixed **mid-build: the user pasted a real API key into `.env.example`** (the git-tracked template) instead of `.env` (gitignored). Checked `git log`/`git status` immediately — confirmed nothing had been committed or pushed, so no real exposure occurred — then corrected both files before continuing. No key rotation was necessary.

### A real finding, not a bug: the maternity leave "done when" example doesn't have an answer in-corpus
SPEC.md's Milestone 3 done-criteria example is "ask about maternity leave, then paternity leave, both retrieve correctly." Live-testing this surfaced something worth recording: **maternity leave doesn't have a specific answer in the ingested corpus either.** The Shops & Commercial Establishments Act, Section 14 ("Annual and Maternity leave") specifies fourteen days for *annual* leave, then in subsection (4) says only: *"Every female employee shall be entitled maternity leave as defined in the Maternity Benefit Ordinance, 1958"* — a cross-reference to a completely different, un-ingested law, with no day-count given. The system correctly refused rather than reporting the annual-leave figure as the maternity-leave answer — this is the refusal logic working exactly as intended (CLAUDE.md: never guess), not a retrieval or generation defect. Confirmed by reading the actual chunk text, not assumed.

Since a demo of two correct refusals doesn't showcase the positive/citation path, also live-tested:
- *"how many days notice for termination"* → correct, fully-cited answer from two acts (Standing Orders Act Schedule Standing Order 16 + Shops Act Section 19, both "one month's notice").
- *"what is the current minimum wage for unskilled workers"* → correct answer (Rs 40,000/month, effective 1 July 2025) citing the OCR'd gazette chunk, **with the `superseded_risk` caveat correctly appended** — the first live end-to-end confirmation that the Milestone 2 gazette-OCR work and Milestone 3 generation logic connect correctly.

### Decisions
- Refusal threshold (12.0) calibrated empirically from Milestone 2's real retrieval scores: relevant results cluster ~4.3–9.7, a deliberately irrelevant query scored ~15.1–15.7 — a clear gap, not a guessed number.
- `.env` loading was silently missing (`python-dotenv` was in `requirements.txt` since Milestone 1 but never actually invoked). Added `load_dotenv()` to `api/main.py`.
- Chased a phantom Unicode bug (`�` appearing in printed/repr'd output around em-dashes) for several minutes before confirming via `'—' in answer` / `'�' in answer` checks that the actual API response data was 100% clean UTF-8 — the corruption was in how a tool's terminal output was being displayed during debugging, not in the application. No code change was needed; noting this so a future session doesn't re-chase the same non-bug.

### What broke / open items
- Visual browser verification initially blocked by this environment's network reliability (Playwright's 183MB Chromium download kept resetting near 0%, same pattern hit earlier with the embedding model) — resolved on a retry with `--dns-result-order=ipv4first`; screenshots confirm the disclaimer banner and refusal styling render correctly with zero console errors.
- Milestone 2's minimum-wage gazette gap (see above) is now fully closed as of the OCR addendum; this milestone's finding is specifically that *maternity* leave duration is a **separate, still-open gap** (Maternity Benefit Ordinance, 1958 is not in the corpus — Phase 2 candidate).

### Metrics
- 37 pytest tests total (9 new for generate/rewrite), all passing, zero real network calls in the suite.
- Provider pivots: Anthropic → Gemini → Groq, 2 fully-implemented-then-abandoned integrations before the working one.
- 4/4 live queries against the real Groq API behaved correctly: 2 correct refusals (maternity, paternity), 2 correct cited answers (termination notice, minimum wage with caveat).
