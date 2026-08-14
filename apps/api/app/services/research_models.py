from __future__ import annotations

from functools import lru_cache
from threading import Lock

from app.config import get_settings


_embedding_lock = Lock()
_reranker_lock = Lock()


def _normalize_market(market: str) -> str:
    return "CN" if str(market).upper() == "CN" else "US"


def model_profile(market: str = "US") -> dict[str, str]:
    settings = get_settings()
    normalized = _normalize_market(market)
    return {
        "market": normalized,
        "embedding_model": settings.research_cn_embedding_model if normalized == "CN" else settings.research_embedding_model,
        "reranker_model": settings.research_cn_reranker_model if normalized == "CN" else settings.research_reranker_model,
        "fts_config": "simple" if normalized == "CN" else "english",
    }


@lru_cache(maxsize=2)
def _embedding_model(market: str = "US"):
    from sentence_transformers import SentenceTransformer

    settings = get_settings()
    return SentenceTransformer(
        model_profile(market)["embedding_model"],
        cache_folder=str(settings.research_model_cache_dir),
    )


@lru_cache(maxsize=2)
def _reranker_model(market: str = "US"):
    from sentence_transformers import CrossEncoder

    settings = get_settings()
    return CrossEncoder(
        model_profile(market)["reranker_model"],
        cache_dir=str(settings.research_model_cache_dir),
        max_length=512,
    )


def embed_texts(texts: list[str], market: str = "US") -> list[list[float]]:
    if not texts:
        return []
    with _embedding_lock:
        embeddings = _embedding_model(_normalize_market(market)).encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
    return [embedding.tolist() for embedding in embeddings]


def rerank_pairs(question: str, passages: list[str], market: str = "US") -> list[float]:
    if not passages:
        return []
    pairs = [[question, passage] for passage in passages]
    with _reranker_lock:
        scores = _reranker_model(_normalize_market(market)).predict(
            pairs,
            batch_size=16,
            show_progress_bar=False,
        )
    return [float(score) for score in scores]
