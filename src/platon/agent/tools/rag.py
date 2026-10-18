from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated

from langchain_core.tools import BaseTool, tool
from pydantic import Field

from platon.agent.tools.common import configure_error_handling
from platon.agent.tools.errors import ToolError
from platon.app_logging import log_call

if TYPE_CHECKING:
    from platon.vectorstore.client_manager import ClientManager


def create_rag_tools(cm: ClientManager, max_output_chars: int = 20_000) -> tuple[BaseTool, ...]:
    """Create tools backed by the private vector-store client."""

    def bounded_results(results):
        if not results:
            return results
        # Chroma chunks are already bounded at ingestion. Keep the passages intact
        # so quotations do not end in the middle of a sentence.
        selected = []
        budget = max(1, max_output_chars - 64)
        for item in results:
            candidate = selected + [item]
            if len(json.dumps(candidate, ensure_ascii=False, default=str)) > budget:
                break
            selected.append(item)
        if len(selected) < len(results):
            if not selected:
                first = results[0]
                selected = [{**first, "document": "[Passage exceeds the tool output budget; narrow the search or increase the budget.]"}]
            selected[-1] = {**selected[-1], "omitted_results": len(results) - len(selected)}
        return selected

    @tool
    @log_call
    def search_collection(
        collection_name: str, query: str,
        n_results: Annotated[int, Field(ge=1, le=50)] = 5,
        rank: bool = False, rerank: bool = False,
        candidate_k: Annotated[int | None, Field(ge=1, le=200)] = None,
        embedding_weight: Annotated[float, Field(ge=0, le=1)] = 0.8,
        semantic_dedup_threshold: Annotated[float | None, Field(ge=0, le=1)] = None,
    ) -> list:
        """Search an existing collection. List collections first if its name is unknown.

        n_results is final K; candidate_k is retrieved K (>= n_results).
        rank adds embedding + reciprocal retrieval-rank scoring; rerank adds
        a multilingual CrossEncoder stage (loaded on first use). Either stage
        defaults to at least 20 candidates. Semantic dedup is opt-in with rank.
        Returns complete passages within the output budget. The final result may
        carry omitted_results; request fewer results when that happens. Distance
        is the Chroma ranking value (lower is better); similarity is a legacy
        value of 1 - distance, not a calibrated relevance score.
        """
        try:
            return bounded_results(cm.search(collection_name, query, n_results, rank=rank, rerank=rerank,
                                             candidate_k=candidate_k, embedding_weight=embedding_weight,
                                             semantic_dedup_threshold=semantic_dedup_threshold))
        except Exception as exc:
            raise ToolError.from_exception(
                "search_collection",
                f"searching collection '{collection_name}'",
                exc,
            ) from exc

    @tool
    @log_call
    def search_all_collections(
        query: str,
        n_results: Annotated[int, Field(ge=1, le=50)] = 5,
        n_results_per_collection: Annotated[int, Field(ge=1, le=50)] = 5,
        rank: bool = False, rerank: bool = False,
        candidate_k: Annotated[int | None, Field(ge=1, le=200)] = None,
        embedding_weight: Annotated[float, Field(ge=0, le=1)] = 0.8,
        semantic_dedup_threshold: Annotated[float | None, Field(ge=0, le=1)] = None,
    ) -> list:
        """Search all existing collections without guessing collection names.

        Final K is n_results. candidate_k overrides the retrieved candidate
        count per collection; rank/rerank default to at least 20 per collection.
        Ranking/reranking runs globally before truncation. Raw mode compares
        reciprocal ranks rather than incompatible cross-collection distances.

        Returns complete passages within the output budget. The final result may
        carry omitted_results; request fewer results when that happens. Distance
        is the Chroma ranking value (lower is better); similarity is a legacy
        value of 1 - distance, not a calibrated relevance score.
        """
        try:
            return bounded_results(cm.search_all(query, n_results, n_results_per_collection,
                                                 rank=rank, rerank=rerank, candidate_k=candidate_k,
                                                 embedding_weight=embedding_weight,
                                                 semantic_dedup_threshold=semantic_dedup_threshold))
        except Exception as exc:
            if hasattr(exc, "partial_results"):
                exc.partial_results = bounded_results(exc.partial_results[:n_results])
            raise ToolError.from_exception(
                "search_all_collections",
                "searching all collections",
                exc,
            ) from exc

    @tool
    @log_call
    def get_list_of_collections() -> list[str]:
        """Get a list of all collection names."""
        try:
            return cm.get_collections()
        except Exception as exc:
            raise ToolError.from_exception(
                "get_list_of_collections",
                "listing collections",
                exc,
            ) from exc

    @tool
    @log_call
    def add_document_to_collection(
        collection_name: str, file_path: str, doc_name: str,
        chunk_size: Annotated[int, Field(ge=1, le=12000)] = 1000,
        chunk_overlap: Annotated[int, Field(ge=0, le=11999)] = 100,
        reindex: bool = False,
    ) -> bool:
        """Ingest with character-based chunking; overlap must be less than size.

        Inspect get_collection_info first. Identical sources/settings reuse
        existing chunks without splitting or embedding. Changed sources/settings
        and legacy collections need explicit reindex=True to replace old chunks.
        """
        try:
            return cm.add_document_to_collection(collection_name, file_path, doc_name,
                                                 chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                                                 reindex=reindex)
        except Exception as exc:
            raise ToolError.from_exception(
                "add_document_to_collection",
                f"adding document '{doc_name}' to collection '{collection_name}'",
                exc,
            ) from exc

    @tool
    @log_call
    def get_collection_info(collection_name: str) -> dict:
        """Inspect an existing collection's chunk count and ingestion manifests.

        Includes source_path for read_file, SHA256, chunk_size/chunk_overlap in
        characters, splitter and embedding model. Missing manifests indicate a
        legacy collection; search it before deciding whether to reindex.
        """
        try:
            return cm.get_collection_info(collection_name)
        except Exception as exc:
            raise ToolError.from_exception("get_collection_info", "reading collection info", exc) from exc

    return tuple(
        configure_error_handling(tool_instance)
        for tool_instance in (
            search_collection,
            search_all_collections,
            get_list_of_collections,
            get_collection_info,
            add_document_to_collection,
        )
    )
