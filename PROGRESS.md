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

---

## Addendum to Milestone 3 — Maternity leave gap closed with the Sindh Maternity Benefits Act, 2018 (2026-07-12)

**Approved scope expansion**: ingest one additional core document to close the maternity-leave gap identified above. The Shops & Commercial Establishments Act's maternity cross-reference points to the un-ingested Maternity Benefit Ordinance, 1958; for Sindh, that Ordinance is superseded by the Sindh Maternity Benefits Act, 2018 (Sindh Act No. XXXIX of 2018), which sets a concrete 16-week entitlement (4 weeks pre-delivery + 12 weeks post-delivery, Section 3).

**Source verification**: two candidate URLs were given. Candidate (a), `clr.org.pk/.../Sindh%20Maternity%20Benefits%20Act,%202018.pdf`, was downloaded to a scratch file, inspected directly with `pypdf`, and confirmed correct before being registered in `ingest/sources.py` — correct act name/number, 14 sections, real extractable text (2391 + 2919 chars across 2 pages, not scanned, no OCR needed), and Section 3 text matching the expected 4-week + 12-week breakdown exactly. The scratch file was deleted after verification. Candidate (b) (sindhlaws.gov.pk) was not needed.

**A real chunker gap, not anticipated**: unlike 5 of the other 6 core documents, this Act's PDF has **no table of contents at all** — section titles appear inline instead, immediately after the section number, ending in a colon (e.g. `"3. Mandatory maternal leave:"`). The existing chunker only looked up titles from a parsed TOC, which would have marked all 14 sections `UNKNOWN — not found in TOC` despite the titles being clearly present in the text. Added a narrowly-scoped `_extract_inline_title()` fallback in `ingest/chunk.py`, wired into `chunk_document()`'s title lookup so it **only activates when the relevant TOC dict is completely empty** — this is deliberate: documents that have a real TOC with a few genuine gaps (Industrial Relations Act, sections 15/40) must keep showing `UNKNOWN_TITLE` for those gaps, never a guessed title. Verified with two new tests in `tests/test_chunk.py`: one confirming the fallback recovers titles on a no-TOC synthetic document, one confirming it does *not* mask a genuine TOC gap on a document that has a real (if incomplete) TOC.

**Pipeline run**: `download` → `parse` (confirmed not scanned, 0% flagged) → `chunk` (14/14 sections got real inline titles, zero `UNKNOWN`) → `index` (235 chunks total, up from 221).

**Live verification — and a real retrieval-ranking finding**: the first live query, phrased `"How much maternity leave do I get under Sindh labor law?"`, **still refused**. Root-caused by inspecting the actual retrieved chunks rather than assuming a bug: the phrase "under Sindh labor law" has enough literal keyword overlap with the generic `"...It shall extend to the whole of the Province of Sindh..."` boilerplate in two unrelated acts' Section 1 ("short title, extent...") that those boilerplate chunks outscored the actually-relevant Maternity Benefits Act Section 3 by a hair (score 6.66/6.73 vs. 6.95), pushing Section 3 just outside the `TOP_K=5` window sent to the LLM — which then correctly refused rather than answer from Sections 7/8/11 (payment/death/penalties) alone, none of which state a duration. Re-tested with more natural phrasings (`"maternity leave"`, `"how many weeks of maternity leave am I entitled to"`, `"maternity benefits leave duration"`) — all three correctly rank Section 3 first. `"how much maternity leave do I get"` end-to-end through `generate_answer` now returns a correct, fully-cited answer: *"four (4) weeks of leave before your expected delivery date and twelve (12) weeks of leave after delivery... sixteen (16) weeks of maternity leave (Sindh Maternity Benefits Act 2018, s. 3, p. 1)"*.

This is a genuine phrasing-sensitivity edge case in dense-retrieval-only search, not a chunking or generation defect — worth carrying into Milestone 4 as an eval question (a query phrased with an incidental jurisdiction keyword) and revisiting once Milestone 5 adds BM25 hybrid search, which should reduce sensitivity to this kind of keyword-overlap-driven ranking noise.

**Self-caught regression, fixed before it reached a commit**: running the full `download → parse → chunk → index` pipeline to pick up the new document silently wiped the gazette notification's OCR'd text — `ingest.parse` re-parses *every* core document with pypdf/pdfplumber (correctly flagging the gazette as scanned, but not OCR'ing it), overwriting the interim JSON that `ingest.ocr_fallback` had previously populated. The gazette chunk ended up with `text: ""`. Caught by inspecting the actual chunk output while gathering source material for the Milestone 4 eval set, not by a test (no test currently asserts non-empty chunk text for this specific doc). Fixed by re-running `python -m ingest.ocr_fallback` (after re-adding Tesseract's winget install path to this shell session's `PATH`, which doesn't persist across sessions) and re-running `chunk`/`index`; verified restored via a direct `retrieval.query` + `generate_answer` check that the minimum-wage caveat answer still works correctly. **Operational takeaway for future sessions**: `ingest.ocr_fallback` must always be re-run after any full `ingest.parse` pass, for as long as the gazette document remains OCR-only — this is a real footgun in the current pipeline design, not just a one-off mistake, and would be worth hardening in a later milestone (e.g. `ingest.parse` skipping/preserving already-OCR'd interim files, or a test asserting no core document's final chunk text is empty).

### Metrics (updated)
- 235 chunks total (221 + 14), all 7 core documents now represented in the corpus.
- 41 pytest tests total (2 new for the inline-title fallback, 1 updated for the new source count), all passing.

---

## Milestone 4 — Evaluation pipeline: eval set + baseline (2026-07-13 to 2026-07-14)

### Built
- `eval/testset.jsonl` — 52 hand-written entries (37 answerable / 10 expected_refusal / 5 follow_up, the last contributing 10 individual turns), covering leave, termination/notice, hours/overtime, minimum wage, deductions/payment timing, unions/disputes, and Roman Urdu phrasings. Every reference answer and `expected_source` was grounded by reading the actual chunk text in `data/processed/`, not guessed from the act names alone.
- `eval/run.py` — runs every entry through the real pipeline (`rewrite_query` → `retrieve` → `generate_answer`) and scores each type by its own method:
  - **answerable**: four RAGAS-style metrics (faithfulness, answer_relevancy, context_precision, context_recall), each scored 0.0–1.0 by an LLM judge.
  - **expected_refusal**: binary correct/incorrect against each question's own `expected_behavior` (some strict — must refuse; some soft — must avoid a specific forbidden pattern, e.g. a rupee figure, even if not a bare refusal).
  - **follow_up**: a check that the rewritten standalone query actually names the right subject, plus the turn's own final-answer score (RAGAS-style or refusal-binary, depending on that turn's `expected_outcome`).
  - Checkpoints every single case to `eval/results/_checkpoint.json` as it goes, so a crash or a deliberate multi-batch run (`python -m eval.run "A1,A2,..."`) never repeats work already paid for in tokens.
- `tests/test_eval_run.py` — 8 new tests for the pure-logic scoring helpers (`score_refusal`, `check_subject_naming`, `_mean`, `summarize`), no live calls.

### Pre-run corrections to the eval set (your review, before any scoring)
1. **R8 (gratuity) was flatly wrong.** Grepping the processed corpus for "gratuity" surfaced real, substantive coverage in `Sindh Terms of Employment (Standing Orders) Act`, Schedule Standing Order 16(6): a full lump-sum entitlement (one month's wages per completed year of service, waived if the employer runs an equal-or-better provident fund). Reclassified as answerable (`A36`); replaced R8 with a verified-absent question about the separate Sindh Prohibition of Employment of Children Act (confirmed not registered in `ingest/sources.py`, and the only related content anywhere in the corpus is the Shops Act's one-line Section 20).
2. **A16** re-verified against the actual Section 7(1) text: the Act fixes the 8:00 p.m. closing time directly, not via a government notification mechanism (Section 4's exemption power is general-purpose, not a rate-setting delegation like the Minimum Wages Board). Reference answer updated to say this explicitly.
3. **`expected_behavior` added to every refusal entry** (standalone and follow-up), each with a `strict_refusal_required` flag: `true` means only an actual refusal counts as correct; `false` (used for R5 and F3-turn2, per your redefinition) means the answer just has to avoid a specific forbidden pattern — e.g. F3-turn2 passes whether it refuses outright or explains the Board-declares-rates mechanism, as long as it never states a skilled-worker rupee figure.
4. **Q51 added** (`known_hard: true`) — `"How many days of annual leave do I get under Sindh labor law?"` — verified empirically *before* adding it that this exact phrasing pushes Shops Act s.14 out of the top-5 retrieval window, tracked explicitly as the before/after case for Milestone 5.

### Baseline results (2026-07-14, judge model `llama-3.1-8b-instant`; `generate_answer` unchanged, `openai/gpt-oss-120b`)

| Category | Metric | Score |
|---|---|---|
| Answerable (n=45, incl. follow-up answerable turns + Q51) | faithfulness | 0.763 |
| | answer_relevancy | 0.804 |
| | context_precision | 0.724 |
| | context_recall | 0.742 |
| Expected refusal (n=12, incl. follow-up refusal turns) | binary accuracy | 0.750 (9/12) |
| Follow-up query rewriting | subject-naming accuracy | 1.000 (10/10) |

Full detail: `eval/results/2026-07-14.json`.

### What the eval actually found — read past the aggregate

**1. The "Sindh"-phrasing retrieval bug (flagged during ingestion) is a real, broader bug class, not a one-off.** `Q51` was the deliberately-tracked known_hard case, but the baseline run also caught **two more instances that weren't flagged in advance**: `A1` ("...under Sindh law?") and `A4` ("...under the Sindh Maternity Benefits Act?") both refused, even though `A4`'s underlying content was manually verified working under slightly different phrasing during the Milestone 3-addendum work two days ago. Root cause confirmed identical each time: mentioning "Sindh" (and especially an Act name + year) pulls in generic "Section 1 — short title, extent, application and commencement" boilerplate from *other* acts, crowding the real answer out of the top-5 window. **A new, more striking instance turned up in the follow-up flow**: `F4-turn2`'s query rewriter correctly identified "temporary" as the subject (subject-naming check passed) but rewrote it into *"Does the Sindh Shops and Commercial Establishments Act 2015 and the Sindh Terms of Employment (Standing Orders) Act 2015 make any distinction..."* — naming two acts and two years — and the resulting retrieval top-5 was **literally Section 1 of five different acts**, nothing else. The rewriter itself can manufacture this failure mode, not just the end user. This is now a well-characterized bug with 4 confirmed reproductions (`A1`, `A4`, `Q51`, `F4-turn2`), a strong, concrete motivation for Milestone 5's hybrid (BM25 + vector) search.

**2. Roman Urdu retrieval is meaningfully weaker than English, right now.** Both Roman Urdu answerable questions failed: `A32` ("Meri salary se kitni katauti ho sakti hai?") and `A33` ("Naukri se nikalte waqt kitne dinon ka notice zaroori hai?") retrieved *completely unrelated* sections (Industrial Relations Act union/strike sections, Maternity Benefits Act's "Overriding effect") — the correct Payment of Wages / Shops Act sections didn't appear anywhere in the top 5. This directly concerns CLAUDE.md's multilingual requirement and is worth its own investigation before claiming Urdu support works, not just a Milestone 5 footnote.

**3. Two plain-English retrieval misses unrelated to the above**: `A17` (continuous-work rest-break question — Shops Act s.7(3) buried in a multi-topic section, out-ranked by other hours/leave sections) and `A36` (the newly-added gratuity question — Standing Order 16(6)'s gratuity clause is deep inside a long, differently-titled "Termination of employment" section and didn't surface in the top 5). These look like chunk-granularity/topic-overlap limitations rather than the "Sindh"-keyword bug — a second, distinct improvement target for Milestone 5.

**4. A second test-design error, same shape as R8's, caught by reading the actual answer**: `R3` ("compensation for permanent disability") was marked `expected_refusal`, but the system correctly answered from Standing Order 12 (Compulsory Group Insurance), which requires insurance "not less than the compensation specified in Schedule IV to the Workmen's Compensation Act, 1923" — a real, substantive, grounded answer. Verified by reading Standing Order 12's full text: this was **my test-design mistake, not a system failure** — I should have grepped for "compensation" the same way I grepped for "gratuity" before finalizing R8. Not yet corrected in `eval/testset.jsonl` — flagging here for your call on whether to reclassify it now or in a follow-up pass.

**5. One genuine, confirmed answer-generation defect, and one false-positive in my own automated check, both found in `R8`'s output:**
   - **Defect**: the generated answer opened with *"The Sindh Prohibition of Employment of Children Act provides that..."* — but its own parenthetical citation correctly names `(Sindh Shops and Commercial Establishments Act 2015, s. 20, p. 13)`. The model echoed the act name from the user's question into its prose instead of naming the act it actually cited — a real citation-fidelity bug in `api/generate.py`'s prompt/behavior, not caught by the existing refusal logic since retrieval did legitimately return a relevant chunk (Shops Act s.20 is real, on-topic content).
   - **Defect**: that same answer carried the `superseded_risk` revision caveat ("rates...may have been revised") despite discussing no rate at all. Confirmed by direct retrieval inspection: the irrelevant gazette-notification chunk (`superseded_risk: True`) was the 5th of 5 retrieved hits, and `generate_answer`'s caveat trigger checks *any* retrieved hit rather than only the hit(s) actually cited in the answer.
   - **False positive**: `F3-turn2`'s automated verdict was FAIL (regex matched a rupee figure), but manual reading shows the answer correctly explains *"wages for skilled and semi-skilled workers...must not be lower than the minimum wage fixed for unskilled workers"* without inventing a skilled-specific figure — it just also correctly restates the real Rs 40,000 unskilled rate as necessary context, which the blunt `fail_regex` couldn't distinguish from a fabricated number. True verdict: **pass**. This is a known, accepted limitation of a regex-based automated check, called out explicitly rather than silently trusted.

### Corrected picture after manual review
- Refusal accuracy: **9/12 automated**, but `R3` is an invalid test (system was actually correct) and `F3-turn2` is a false-positive fail (system was actually correct) → **true accuracy is ~10/10 on the valid, correctly-scored cases**, with `R3` needing a testset fix before it can be counted at all.
- Answerable: 8/45 refused (17.8%) breaks down as 4 confirmed "Sindh"-phrasing collisions, 2 Roman Urdu failures, 2 plain-English chunk-granularity misses — a genuinely useful, categorized failure map for Milestone 5, not a single fuzzy number.

### Ragas — a real, verified environment blocker (not a preference)
Installing `ragas` (0.4.3, the only version on PyPI) **silently corrupted this project's numpy install** — no prebuilt numpy wheel exists for Python 3.13, so pip fell back to building numpy from source, producing a broken MinGW build that segfaulted on a bare `import numpy` (which would have broken embeddings/retrieval/chromadb project-wide, not just eval). Caught immediately, fixed by pinning `numpy==2.2.6` (real cp313 wheels), and re-verified the full test suite plus a live retrieval query before continuing. Separately, `ragas` itself has a hard, unconditional import of an unused Google Vertex AI integration that no longer exists in current `langchain-community` — pinning an older `langchain-community` to work around it then collides with the newer `langchain-core` the same install pulled in (metaclass conflict). Per your explicit decision, `eval/run.py` implements the same four metrics directly as LLM-judge prompts against the project's existing Groq client instead of fighting the dependency chain further; the broken `ragas`/`langchain*` packages were fully uninstalled afterward and the environment re-verified clean (39 tests passing, live Groq call working) before proceeding.

### Groq free-tier daily quota — also real, also worth recording
Mid-run, `openai/gpt-oss-120b` (the answer-generation model) hit Groq's free-tier **daily token cap** (200,000/day), largely consumed by this session's own extensive live-testing. Rate-limit waits escalated past 25 minutes before a UTC day rollover reset the quota. Fixed two ways: (1) added retry-with-backoff to `eval/run.py` that parses Groq's suggested wait time and retries automatically (caught actual 429s during this run, confirmed working); (2) switched `JUDGE_MODEL` to `llama-3.1-8b-instant`, which draws from a separate per-model quota and is well-suited to structured scoring, so judging no longer competes with `generate_answer`'s own token budget. The full 52-entry run then completed cleanly across 4 batches with only one transient rate-limit retry.

### Metrics
- 52 eval entries (37 answerable / 10 expected_refusal / 5 follow_up = 10 turns), 45 scored cases + 12 refusal cases + 10 subject-naming checks.
- 47 pytest tests total (8 new for `eval/run.py`'s scoring logic), all passing.
- Baseline recorded above is the number Milestone 5's hybrid search needs to beat — both the aggregate and, more importantly, the 8 named failing questions and their 3 distinct root causes.

### What broke / open items
- `R3` needs reclassification in `eval/testset.jsonl` (same fix pattern as R8) — not yet done, flagged for your decision.
- Two real `api/generate.py` bugs found (citation act-name fidelity; `superseded_risk` caveat triggering on unused retrieved chunks, not just cited ones) — not yet fixed, flagged for your decision on priority.
- Roman Urdu retrieval quality is a real, separate concern from the "Sindh"-keyword bug and may need its own investigation (e.g. checking the embedding model's Roman Urdu training coverage) rather than assuming Milestone 5's hybrid search alone will fix it.
