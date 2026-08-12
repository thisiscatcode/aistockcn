from __future__ import annotations

from functools import lru_cache
from threading import Lock

from app.config import get_settings


_embedding_lock = Lock()
_reranker_lock = Lock()


@lru_cache(maxsize=1)
def _embedding_model():
    from sentence_transformers import SentenceTransformer

    settings = get_settings()
    return SentenceTransformer(
        settings.research_embedding_model,
        cache_folder=str(settings.research_model_cache_dir),
    )


@lru_cache(maxsize=1)
def _reranker_model():
    from sentence_transformers import CrossEncoder

    settings = get_settings()
    return CrossEncoder(
        settings.research_reranker_model,
        cache_dir=str(settings.research_model_cache_dir),
        max_length=512,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    with _embedding_lock:
        embeddings = _embedding_model().encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
    return [embedding.tolist() for embedding in embeddings]


def rerank_pairs(question: str, passages: list[str]) -> list[float]:
    if not passages:
        return []
    pairs = [[question, passage] for passage in passages]
    with _reranker_lock:
        scores = _reranker_model().predict(
            pairs,
            batch_size=16,
            show_progress_bar=False,
        )
    return [float(score) for score in scores]
