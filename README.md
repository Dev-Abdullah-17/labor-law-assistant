# Labor Law Assistant (Sindh, Pakistan)

A RAG-based chatbot that answers questions about Pakistani (Sindh + selected federal) labor law, with citations to the exact act, section, and page. Portfolio project — see `SPEC.md` for the full build plan and `PROGRESS.md` for the milestone-by-milestone build log.

**Status:** Milestone 1 complete — project skeleton + document ingestion (download + per-page parsing).

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
