"""Lazy, in-memory BM25 index over every chunk's text.

Loaded once per process and cached (same singleton pattern as
retrieval.embed's model), rebuilt from data/processed/*.json — the corpus
is small (~250 chunks), so there's no need for a separate persisted index
or build step the way the vector store has one.

BM25 is what makes hybrid search useful: it weights terms by how rare
they are across the corpus, so ubiquitous boilerplate ("Sindh", "Act",
"2015" — present in nearly every chunk) contributes almost nothing to a
match, while rare, specific terms ("maternity", "retrenchment", "gratuity")
dominate the ranking. That is the opposite failure mode from the dense
vector search's, which was found (Milestone 4) to rank generic
"short title" chunks *above* the genuinely relevant section for exactly
these Sindh/Act/year-heavy queries.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from ingest.sources import core_sources

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class Bm25Index:
    """Holds the BM25 model alongside the chunk records it was built from,
    so search results can be mapped back to full chunk dicts."""

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self._corpus_tokens = [_tokenize(c["text"]) for c in chunks]
        self._bm25 = BM25Okapi(self._corpus_tokens) if chunks else None

    def search(self, question: str, top_k: int, act_name: str | None = None) -> list[tuple[dict, float]]:
        """Return up to top_k (chunk, bm25_score) pairs, higher score first."""
        if self._bm25 is None:
            return []

        scores = self._bm25.get_scores(_tokenize(question))
        ranked = sorted(
            ((chunk, score) for chunk, score in zip(self.chunks, scores)),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if act_name:
            ranked = [pair for pair in ranked if pair[0]["act_name"] == act_name]
        return ranked[:top_k]


def _load_all_chunks() -> list[dict]:
    chunks: list[dict] = []
    for source in core_sources():
        path = PROCESSED_DIR / f"{source.doc_id}.json"
        if not path.exists():
            continue
        chunks.extend(json.loads(path.read_text(encoding="utf-8")))
    return chunks


_index: Bm25Index | None = None


def get_index() -> Bm25Index:
    global _index
    if _index is None:
        _index = Bm25Index(_load_all_chunks())
    return _index
