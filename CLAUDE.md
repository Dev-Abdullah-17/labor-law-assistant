# Labor Law Assistant (Sindh, Pakistan) — Project Rules

## What this project is
A RAG-based chatbot that answers questions about Pakistani (Sindh + federal) labor law
with citations to the exact act, section, and page. Built as a portfolio project that
must look production-quality, not tutorial-quality.

Read SPEC.md for the full build plan and follow it milestone by milestone.
Do NOT skip ahead — complete and verify each milestone before starting the next.

## Tech stack (do not substitute without asking)
- Python 3.11+
- LangChain OR plain Python (prefer plain Python + direct SDK calls where simple)
- ChromaDB for the vector store (local, persistent)
- Embeddings: a multilingual sentence-transformers model
  (e.g. paraphrase-multilingual-mpnet-base-v2) so Urdu/Roman Urdu queries work
- BM25 via rank_bm25 for hybrid search (Milestone 4)
- FastAPI backend + minimal HTML/JS frontend (no heavy framework)
- RAGAS for evaluation
- pypdf / pdfplumber for PDF parsing

## Hard rules
- Every answer the chatbot gives MUST include citations: act name, section number, page.
- If retrieval confidence is low, the bot must say "I could not find this in the
  ingested laws" — never guess legal content.
- Every chunk stored in the vector DB must carry metadata:
  {act_name, act_year, section_number, section_title, page, source_url, version_date}
- Chunking is section-aware: never split a legal section mid-way unless it exceeds
  the max chunk size; then split on sub-clauses with overlap.
- Scope disclaimer in the UI: "Covers Sindh provincial + selected federal law only.
  Not legal advice."
- Write tests for the chunker and the retrieval layer (pytest).
- Keep secrets in .env, never hardcode API keys.
- After each milestone, update PROGRESS.md with what was built, what broke,
  and any metric numbers (this becomes the portfolio case study).

## Style
- Type hints everywhere, docstrings on public functions.
- Small modules: ingest/, retrieval/, api/, eval/, frontend/
- Prefer readable code over clever code — this repo will be read by recruiters.
