"""Thread-safe loading of local embedding models shared by RAG and web search."""

from __future__ import annotations

import gc
from functools import lru_cache
from threading import RLock
from typing import Any

from sentence_transformers import SentenceTransformer

from platon.app_logging import LOGGER, log_call

# it should be transformed to config...
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_EMBEDDING_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
DEFAULT_EMBEDDING_DEVICE = "cpu"

_MODEL_LOAD_LOCK = RLock()

@lru_cache(maxsize=1)
@log_call
def _load_embedding_model(
    model_name: str,
    device: str,
    revision: str,
) -> SentenceTransformer:
    """Construct one fully materialized SentenceTransformer instance."""
    LOGGER.info("Loading embedding model (device=%s)", device)
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
            LOGGER.warning("Embedding model initialization hit a meta tensor issue; retrying once")
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
    LOGGER.info("Embedding model loaded successfully")
    return model


@log_call
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


@lru_cache(maxsize=1)
def _load_reranking_model():
    from sentence_transformers import CrossEncoder
    return CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", device="cpu")


def get_reranking_model():
    """Load the optional multilingual reranker once, only on explicit use."""
    with _MODEL_LOAD_LOCK:
        return _load_reranking_model()
