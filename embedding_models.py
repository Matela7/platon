"""Thread-safe loading of local embedding models shared by RAG and web search."""

from __future__ import annotations

import gc
from functools import lru_cache
from threading import RLock
from typing import Any

from sentence_transformers import SentenceTransformer


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DEFAULT_EMBEDDING_DEVICE = "cpu"

_MODEL_LOAD_LOCK = RLock()


@lru_cache(maxsize=4)
def _load_embedding_model(
    model_name: str,
    device: str,
    revision: str,
) -> SentenceTransformer:
    """Construct one fully materialized SentenceTransformer instance."""
    for attempt in range(2):
        try:
            model = SentenceTransformer(
                model_name,
                device=device,
                revision=revision,
            )
            break
        except NotImplementedError as exc:
            is_meta_tensor_error = "meta tensor" in str(exc).lower()
            if not is_meta_tensor_error or attempt == 1:
                raise
            gc.collect()

    meta_parameters = [
        name
        for name, parameter in model.named_parameters()
        if getattr(parameter, "is_meta", False)
    ]
    if meta_parameters:
        names = ", ".join(meta_parameters[:5])
        raise RuntimeError(
            "Embedding model contains unmaterialized meta parameters: "
            f"{names}"
        )
    return model


def get_embedding_model(
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    *,
    device: str = DEFAULT_EMBEDDING_DEVICE,
    revision: str = DEFAULT_EMBEDDING_REVISION,
) -> SentenceTransformer:
    """Return a cached model without allowing concurrent first initialization."""
    with _MODEL_LOAD_LOCK:
        return _load_embedding_model(model_name, device, revision)


def clear_embedding_model_cache() -> None:
    """Clear cached models for tests or an explicit application reload."""
    with _MODEL_LOAD_LOCK:
        _load_embedding_model.cache_clear()


def embedding_model_cache_info() -> Any:
    """Expose cache statistics for diagnostics."""
    with _MODEL_LOAD_LOCK:
        return _load_embedding_model.cache_info()
