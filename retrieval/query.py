"""CLI: query the vector store and print the top-5 matching chunks.

Usage: python -m retrieval.query "how many days notice for termination"

This is Milestone 2's retrieval-only tool — it prints scored chunks with
their citation metadata but does not generate an answer (that's Milestone 3).
"""

from __future__ import annotations

import argparse
import sys

import chromadb

from retrieval.embed import embed_texts
from retrieval.index import CHROMA_DIR, COLLECTION_NAME

TOP_K = 5


def query(question: str, top_k: int = TOP_K) -> list[dict]:
    """Return the top_k chunks most similar to `question`, each with its score and metadata."""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_collection(COLLECTION_NAME)

    [query_embedding] = embed_texts([question])
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)

    hits = []
    for i in range(len(results["ids"][0])):
        hits.append(
            {
                "score": results["distances"][0][i],
                "metadata": results["metadatas"][0][i],
                "text": results["documents"][0][i],
            }
        )
    return hits


def _print_hits(question: str, hits: list[dict]) -> None:
    print(f'Query: "{question}"\n')
    for rank, hit in enumerate(hits, start=1):
        meta = hit["metadata"]
        snippet = " ".join(hit["text"].split())[:220]
        print(f"[{rank}] score={hit['score']:.4f}  {meta['act_name']} ({meta['act_year']}), "
              f"{meta['section_number']} — {meta['section_title']}, p.{meta['page']}")
        print(f"    {snippet}...")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Natural-language question to search for")
    args = parser.parse_args()

    hits = query(args.question)
    if not hits:
        print("No results — has `python -m retrieval.index` been run?")
        return 1

    _print_hits(args.question, hits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
