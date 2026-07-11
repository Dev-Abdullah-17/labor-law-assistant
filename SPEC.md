# SPEC.md — Labor Law Assistant Build Plan

Build this in order. Each milestone ends with a working, testable state.

---

## Milestone 1 — Project skeleton + document ingestion

1. Create project structure:
   ```
   labor-law-assistant/
   ├── ingest/          # PDF download, parsing, chunking
   ├── retrieval/       # vector + hybrid search
   ├── api/             # FastAPI app
   ├── eval/            # test set + RAGAS pipeline
   ├── frontend/        # single-page chat UI
   ├── data/raw/        # downloaded PDFs
   ├── data/processed/  # chunked JSON
   ├── tests/
   ├── CLAUDE.md, SPEC.md, PROGRESS.md, README.md, requirements.txt, .env.example
   ```

2. Download these documents into data/raw/ (write a download script with the URLs
   listed; if a URL fails, tell me instead of guessing an alternative):
   - Sindh Terms of Employment (Standing Orders) Act, 2015
     — sindhlaws.gov.pk (Sindh Code portal) or ILO NATLEX:
       https://www.ilo.org/dyn/natlex/docs/ELECTRONIC/102140/123386/F603171926/PAK102140.pdf
   - Sindh Shops & Commercial Establishment Act, 2015 — sindhlaws.gov.pk
   - Sindh Minimum Wages Act, 2015 + latest minimum wage gazette notification
   - Sindh Payment of Wages Act, 2015 — sindhlaws.gov.pk
   - Sindh Industrial Relations Act, 2013 —
     https://sindhhighcourt.gov.pk/downloads/source_files/Sindh%20Industrial%20Relation%20Act,%202013.pdf
     NOTE: check whether the Sindh Industrial Relations Act 2021 (clr.org.pk) supersedes
     it; ingest the latest consolidated version and record version_date in metadata.
   - (Phase 2, skip for now): Sindh Factories Act 2015, Sindh Employees Old-Age
     Benefits Act 2014, Sindh Workers Compensation Act 2015.

3. Parse PDFs. Detect whether each PDF is text-native or scanned. If scanned,
   flag it in PROGRESS.md and try the ILO NATLEX version instead (better OCR).

**Done when:** `python -m ingest.download && python -m ingest.parse` produces
clean per-page text with page numbers preserved.

---

## Milestone 2 — Section-aware chunking + vector store

1. Write a chunker that:
   - Detects legal section boundaries via regex on headings like
     `^\s*(\d+[A-Z]?)\.\s+` and ALL-CAPS/numbered headings; keep each section intact.
   - Splits oversized sections (> ~1200 tokens) on sub-clauses (a), (b), (i), (ii)
     with 100-token overlap.
   - Attaches full metadata to every chunk (see CLAUDE.md hard rules).
2. Write pytest tests: feed a sample act excerpt, assert no section is split
   mid-sentence and metadata is correct.
3. Embed chunks with the multilingual model and persist to ChromaDB.
4. Build a small CLI: `python -m retrieval.query "how many days notice for termination"`
   prints top-5 chunks with scores + metadata.

**Done when:** the CLI returns relevant sections with correct section numbers
for 5 manual test queries.

---

## Milestone 3 — Answer generation with citations + chat API/UI

1. Generation: given top-k chunks, produce an answer that
   - cites like: (Sindh Standing Orders Act 2015, s. 12, p. 8)
   - refuses when max retrieval score is below a threshold.
2. FastAPI endpoints: POST /chat (message + history), GET /health.
3. Query rewriting: rewrite follow-up questions into standalone queries
   using chat history before retrieval.
4. Minimal frontend: chat window, source citations rendered as expandable
   cards showing the actual section text, scope disclaimer banner.

**Done when:** I can ask "how much maternity leave do I get?" then
"and what about paternity?" in the UI and both retrieve correctly.

---

## Milestone 4 — Evaluation pipeline (the differentiator)

1. Create eval/testset.jsonl with 50 Q-A pairs I will help write —
   generate a first draft of 50 realistic questions (leave, termination notice,
   overtime, minimum wage, working hours, deductions, maternity leave, EOBI)
   with reference answers + the act/section they come from, and STOP so I can
   review/correct them before running eval.
2. RAGAS pipeline measuring: faithfulness, answer relevancy, context precision,
   context recall. Save results to eval/results/<date>.json.
3. Record the baseline in PROGRESS.md.

**Done when:** `python -m eval.run` prints a metrics table and saves results.

---

## Milestone 5 — Hybrid search + measured improvement

1. Add BM25 alongside vector search; merge with reciprocal rank fusion.
2. Re-run the eval. Record before/after metrics in PROGRESS.md.
3. Add metadata filtering (filter by act) to the API and UI.

**Done when:** eval shows measurable change (better or worse — record honestly)
and the README explains the result.

---

## Milestone 6 — Case-study README + polish

Rewrite README.md as a portfolio case study:
problem → architecture diagram → key decisions & trade-offs (chunking strategy,
embedding model choice, hybrid search) → what broke and how it was fixed
(pull from PROGRESS.md) → eval numbers before/after → limitations → roadmap.
Add screenshots of the UI. Add a 60-second demo GIF if possible.
