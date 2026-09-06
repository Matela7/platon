from __future__ import annotations

from typing import Any, Sequence

from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

from embedding_models import get_embedding_model
from websearch.websearch_parameters import WebSearchParameters
from websearch.utils import (
    _deduplicate_exact,
    cosine_similarity,
    result_to_text,
    semantic_deduplicate,
)


def rank_results(
    query: str,
    results: list[dict[str, Any]],
    *,
    top_k: int = 5,
    embedding_weight: float = 0.8,
    semantic_dedup_threshold: float | None = 0.96,
) -> list[dict[str, Any]]:
    """Deduplicate and rank DuckDuckGo results with a hybrid score."""
    if not 0.0 <= embedding_weight <= 1.0:
        raise ValueError("embedding_weight must be between 0 and 1")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    unique_results = _deduplicate_exact(results)
    if not unique_results:
        return []

    texts = [query, *(result_to_text(result) for result in unique_results)]
    vectors = get_embedding_model().encode(texts, normalize_embeddings=True)
    query_vector = vectors[0]
    document_vectors: list[Sequence[float]] = list(vectors[1:])

    if semantic_dedup_threshold is not None:
        unique_results, document_vectors = semantic_deduplicate(
            unique_results,
            document_vectors,
            semantic_dedup_threshold,
        )

    ranked_results: list[dict[str, Any]] = []
    position_weight = 1.0 - embedding_weight
    for result, vector in zip(unique_results, document_vectors, strict=True):
        original_position = int(result["original_position"])
        similarity = cosine_similarity(query_vector, vector)
        ddg_score = 1.0 / (original_position + 1)
        final_score = embedding_weight * similarity + position_weight * ddg_score
        ranked_results.append(
            {
                **result,
                "similarity_score": similarity,
                "ddg_score": ddg_score,
                "final_score": final_score,
            }
        )

    ranked_results.sort(key=lambda result: result["final_score"], reverse=True)
    top_results = ranked_results[:top_k]
    for rank, result in enumerate(top_results, start=1):
        result["rank"] = rank
    return top_results


class WebSearch:
    def __init__(self, parameters: WebSearchParameters):
        self.parameters = parameters

        self.query = parameters.query
        self.max_results = parameters.max_results
        self.wrapper = DuckDuckGoSearchAPIWrapper(
            region=parameters.region,
            safesearch=parameters.safesearch,
            time=parameters.time,
            source=parameters.source,
            max_results=parameters.max_results,
        )

    def search(self) -> list[dict[str, Any]]:
        """Retrieve DuckDuckGo candidates and return reranked results."""
        results = self.wrapper.results(
            self.query,
            max_results=self.max_results,
            source=self.parameters.source,
        )
        return rank_results(
            self.query,
            results,
            top_k=self.parameters.top_k,
            embedding_weight=self.parameters.embedding_weight,
            semantic_dedup_threshold=self.parameters.semantic_dedup_threshold,
        )
