"""Shared embedding model wrapper.

Both retrieval.index (embeds and persists chunks) and retrieval.query
(embeds a user question) must use the exact same model so vectors are
comparable, hence this thin shared wrapper rather than each module loading
its own model instance.
"""

from __future__ import annotations

from sentence_transformers import SentenceTransformer

MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts into vectors using the shared multilingual model."""
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    return [vector.tolist() for vector in embeddings]
