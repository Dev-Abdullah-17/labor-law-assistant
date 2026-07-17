# Labor Law Assistant (Sindh, Pakistan)

A RAG-based chatbot that answers questions about Pakistani (Sindh + selected federal) labor law, with citations to the exact act, section, and page. Portfolio project — see `SPEC.md` for the full build plan and `PROGRESS.md` for the milestone-by-milestone build log.

**Status:** Milestone 5 complete — hybrid search (BM25 + vector, reciprocal rank fusion), Roman Urdu/Urdu query translation, and metadata filtering by Act.

**Scope disclaimer:** Covers Sindh provincial + selected federal law only. Not legal advice.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
```

## Running ingestion

```bash
python -m ingest.download   # downloads core source PDFs into data/raw/
python -m ingest.parse      # extracts per-page text into data/interim/
```

Each command prints a summary table and exits non-zero if any document needs attention (a failed download, a missing URL, or a likely-scanned PDF) — check `data/raw/download_manifest.json` and `data/interim/parse_report.json` for details, and `PROGRESS.md` for the current list of open items.

## Tests

```bash
pytest
```

## Milestone 5 — hybrid search result

Milestone 4's eval baseline found that pure vector search reliably mis-ranked queries mentioning "Sindh" or a full Act name — the generic "short title" section of an unrelated Act would outrank the actually-relevant section, because dense embeddings have no way to down-weight boilerplate terms that appear in nearly every document. Milestone 5 added BM25 (which naturally down-weights common terms via IDF) merged with the existing vector search using reciprocal rank fusion.

**Measured result** (`eval/results/2026-07-17.json`, full detail in `PROGRESS.md`):

| Metric | Before (vector only) | After (hybrid) |
|---|---|---|
| Faithfulness | 0.763 | **0.900** |
| Answer relevancy | 0.841 | **0.948** |
| Context precision | 0.724 | **0.829** |
| Context recall | 0.746 | **0.874** |

All 6 individually-tracked failure cases from the baseline (queries like *"How many days of annual leave do I get under Sindh labor law?"*) now retrieve and answer correctly. Not everything improved: 3 other questions that passed before now fail (recorded honestly in `PROGRESS.md`, not hidden), including one — gratuity — that was already failing before hybrid search and isn't fixed by it, since it's a chunk-granularity issue rather than the keyword-collision problem hybrid search targets.

Milestone 5 also added a Roman Urdu / Urdu translation step ahead of retrieval (diagnosed first: the multilingual embedding model underperforms on this legal corpus even in proper Urdu script, and BM25 offers no help at all since the corpus is English-only — translating to English before retrieval was the fix that actually worked) and metadata filtering by Act, available both via the API (`act_filter` on `POST /chat`, `GET /acts`) and the chat UI's dropdown.

## Project structure

## Project structure

```
labor-law-assistant/
├── ingest/          # PDF download, parsing, chunking
├── retrieval/        # vector + hybrid search (Milestone 2+)
├── api/                # FastAPI app (Milestone 3+)
├── eval/                 # test set + RAGAS pipeline (Milestone 4+)
├── frontend/               # single-page chat UI (Milestone 3+)
├── data/raw/                 # downloaded PDFs (gitignored)
├── data/interim/               # per-page parsed text (gitignored)
├── data/processed/               # chunked JSON (Milestone 2+)
└── tests/
```

## Docs
- [SPEC.md](SPEC.md) — full milestone-by-milestone build plan
- [PROGRESS.md](PROGRESS.md) — what was built, what broke, metrics per milestone
- [CLAUDE.md](CLAUDE.md) — project rules and hard requirements

A full case-study rewrite of this README (architecture, key decisions, eval results, limitations) happens in Milestone 6, once there's an end-to-end system to describe.
