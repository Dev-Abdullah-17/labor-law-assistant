"""Embed chunks and persist them to a local ChromaDB collection.

Usage: python -m retrieval.index

Reads every data/processed/<doc_id>.json produced by ingest.chunk, embeds
each chunk's text with the shared multilingual model, and (re)builds a
persistent Chroma collection at data/chroma/. Idempotent: re-running drops
and rebuilds the collection so it always reflects the current contents of
data/processed/.
"""

from __future__ import annotations

import json
from pathlib import Path

import chromadb

from ingest.sources import core_sources
from retrieval.embed import embed_texts

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
CHROMA_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma"
COLLECTION_NAME = "labor_law_chunks"

METADATA_FIELDS = (
    "act_name",
    "act_year",
    "section_number",
    "section_title",
    "page",
    "source_url",
    "version_date",
    "ocr",
    "superseded_risk",
)


def _load_all_chunks() -> list[dict]:
    chunks: list[dict] = []
    for source in core_sources():
        path = PROCESSED_DIR / f"{source.doc_id}.json"
        if not path.exists():
            continue
        chunks.extend(json.loads(path.read_text(encoding="utf-8")))
    return chunks


def _clean_metadata(chunk: dict) -> dict:
    """Chroma metadata values must be str/int/float/bool, never None."""
    return {field: chunk.get(field) if chunk.get(field) is not None else "" for field in METADATA_FIELDS}


def build_index() -> int:
    """Embed every chunk and (re)build the persistent Chroma collection."""
    chunks = _load_all_chunks()
    if not chunks:
        return 0

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # collection didn't exist yet — nothing to drop
    collection = client.create_collection(COLLECTION_NAME)

    ids = [c["chunk_id"] for c in chunks]
    texts = [c["text"] for c in chunks]
    metadatas = [_clean_metadata(c) for c in chunks]
    embeddings = embed_texts(texts)

    collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
    return len(chunks)


def main() -> int:
    count = build_index()
    print(f"Indexed {count} chunks into {CHROMA_DIR} (collection={COLLECTION_NAME!r}).")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
