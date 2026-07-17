"""CLI: query the hybrid (vector + BM25) search and print the top-5 chunks.

Usage: python -m retrieval.query "how many days notice for termination"
       python -m retrieval.query "..." --act "Sindh Shops and Commercial Establishments Act"

Milestone 2 built pure vector search. Milestone 4's eval baseline found a
real, reproducible failure mode: queries mentioning "Sindh" and/or an Act
name (e.g. "...under Sindh labor law?") rank generic "short title" chunks
from unrelated acts above the actually-relevant section, because dense
embeddings have no mechanism to down-weight ubiquitous boilerplate terms.
Milestone 5 adds BM25 (which naturally down-weights common terms via IDF)
merged with the vector results via reciprocal rank fusion (RRF).

A real finding while wiring this up: RRF's fused score is *rank*-based, not
relevance-calibrated — measuring it against known-relevant vs. deliberately
irrelevant queries (see PROGRESS.md) showed their score ranges genuinely
overlap, with no separating gap the way Milestone 3's raw Chroma distance
had one. RRF is used here purely to decide *which* chunks to surface and in
what order; it is not a substitute for a relevance-confidence signal. Each
hit therefore also carries `vector_distance` — the raw Chroma distance, if
the chunk was found by the vector search at all — so api.generate's
refusal threshold (calibrated in Milestone 3, still valid) keeps working
against the same well-understood metric it always has.
"""

from __future__ import annotations

import argparse
import sys

import chromadb

from retrieval.bm25_index import get_index as get_bm25_index
from retrieval.embed import embed_texts
from retrieval.index import CHROMA_DIR, COLLECTION_NAME, METADATA_FIELDS

TOP_K = 5
FUSION_CANDIDATES = 20
RRF_K = 60


def _vector_search(question: str, top_k: int, act_name: str | None) -> list[tuple[str, dict, str, float]]:
    """Return [(chunk_id, metadata, text, distance), ...] ranked best-first by Chroma distance."""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_collection(COLLECTION_NAME)

    [query_embedding] = embed_texts([question])
    where = {"act_name": act_name} if act_name else None
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k, where=where)

    ranked = []
    for i in range(len(results["ids"][0])):
        ranked.append((
            results["ids"][0][i],
            results["metadatas"][0][i],
            results["documents"][0][i],
            results["distances"][0][i],
        ))
    return ranked


def _bm25_search(question: str, top_k: int, act_name: str | None) -> list[tuple[str, dict, str, float | None]]:
    """Return [(chunk_id, metadata, text, None), ...] ranked best-first by BM25 score.

    The distance slot is always None here — BM25 doesn't produce a distance
    comparable to Chroma's, and the refusal signal deliberately only trusts
    the vector search's calibrated metric (see module docstring).
    """
    pairs = get_bm25_index().search(question, top_k, act_name=act_name)
    ranked = []
    for chunk, _score in pairs:
        metadata = {field: chunk.get(field) if chunk.get(field) is not None else "" for field in METADATA_FIELDS}
        ranked.append((chunk["chunk_id"], metadata, chunk["text"], None))
    return ranked


def _reciprocal_rank_fusion(
    *ranked_lists: list[tuple[str, dict, str, float | None]]
) -> list[tuple[str, dict, str, float | None, float]]:
    """Merge ranked lists by chunk_id using RRF: score = sum(1 / (RRF_K + rank)).

    Higher fused score is better. A chunk appearing near the top of even one
    list, or moderately in both, outranks one appearing only deep in a
    single list — the point of fusing two independent, differently-biased
    rankings rather than trusting either alone. The vector_distance carried
    alongside is whichever list first provided a non-None one (only the
    vector list ever does).
    """
    fused: dict[str, float] = {}
    lookup: dict[str, tuple[dict, str, float | None]] = {}

    for ranked in ranked_lists:
        for rank, (chunk_id, metadata, text, distance) in enumerate(ranked, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            if chunk_id not in lookup:
                lookup[chunk_id] = (metadata, text, distance)
            elif lookup[chunk_id][2] is None and distance is not None:
                lookup[chunk_id] = (lookup[chunk_id][0], lookup[chunk_id][1], distance)

    ordered = sorted(fused.items(), key=lambda pair: pair[1], reverse=True)
    return [
        (chunk_id, lookup[chunk_id][0], lookup[chunk_id][1], lookup[chunk_id][2], score)
        for chunk_id, score in ordered
    ]


def query(question: str, top_k: int = TOP_K, act_name: str | None = None) -> list[dict]:
    """Return the top_k chunks for `question`, fusing vector + BM25 search.

    Each hit carries:
    - "score": `-fused_rrf_score` (lower is "more relevant" by rank fusion) —
      used to decide which chunks to show the LLM and in what order.
    - "vector_distance": the raw Chroma distance if the vector search found
      this chunk, else None — this is what api.generate's refusal threshold
      checks, not "score" (see module docstring for why).
    """
    vector_hits = _vector_search(question, FUSION_CANDIDATES, act_name)
    bm25_hits = _bm25_search(question, FUSION_CANDIDATES, act_name)
    fused = _reciprocal_rank_fusion(vector_hits, bm25_hits)

    hits = []
    for chunk_id, metadata, text, vector_distance, rrf_score in fused[:top_k]:
        hits.append({"score": -rrf_score, "vector_distance": vector_distance, "metadata": metadata, "text": text})
    return hits


def _print_hits(question: str, hits: list[dict]) -> None:
    print(f'Query: "{question}"\n')
    for rank, hit in enumerate(hits, start=1):
        meta = hit["metadata"]
        snippet = " ".join(hit["text"].split())[:220]
        dist = hit["vector_distance"]
        dist_str = f"{dist:.4f}" if dist is not None else "n/a (BM25-only)"
        print(f"[{rank}] rrf_score={hit['score']:.5f}  vector_distance={dist_str}  "
              f"{meta['act_name']} ({meta['act_year']}), "
              f"{meta['section_number']} — {meta['section_title']}, p.{meta['page']}")
        print(f"    {snippet}...")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Natural-language question to search for")
    parser.add_argument("--act", dest="act_name", default=None, help="Restrict results to this exact act_name")
    args = parser.parse_args()

    hits = query(args.question, act_name=args.act_name)
    if not hits:
        print("No results — has `python -m retrieval.index` been run?")
        return 1

    _print_hits(args.question, hits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
