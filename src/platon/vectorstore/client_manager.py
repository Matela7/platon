from __future__ import annotations

from typing import TYPE_CHECKING, Any

from platon.app_logging import LOGGER, log_call
from platon.vectorstore.errors import VectorStoreError
if TYPE_CHECKING:
    from platon.vectorstore.collection_store import CollectionStore


class ClientManager:
    """Lazily manage Chroma collections for the database agent."""

    def __init__(self, persist_dir: str = "./chroma_data") -> None:
        self.persist_dir = persist_dir
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        """Open Chroma lazily when the database agent first needs it."""
        if self._client is None:
            LOGGER.info("Opening vector store client")
            from platon.vectorstore.chroma_utils import start_chromadb

            try:
                self._client = start_chromadb(self.persist_dir)
            except Exception as exc:
                raise VectorStoreError("opening database", exc) from exc
        return self._client

    def get_collection(self, name: str) -> CollectionStore:
        """Return a lazy collection handle; only ingestion creates collections."""
        from platon.vectorstore.collection_store import CollectionStore

        return CollectionStore(self.client, name)

    def get_collections(self) -> list[str]:
        """List all collection names."""
        try:
            return [coll.name for coll in self.client.list_collections()]
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError("listing collections", exc) from exc

    def get_collection_info(self, name: str) -> dict:
        """Inspect chunking settings, fingerprints and source paths for an existing collection."""
        return self.get_collection(name).info()

    @log_call
    def add_document_to_collection(
        self,
        collection_name: str,
        file_path: str,
        doc_name: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
        reindex: bool = False,
    ) -> bool:
        """Add a document to a specific collection.

        Returns True on success; raises VectorStoreError on failure.
        """
        collection = self.get_collection(collection_name)
        LOGGER.info("Ingesting document into collection '%s'", collection_name)
        collection.add_document(file_path, doc_name, chunk_size=chunk_size, chunk_overlap=chunk_overlap, reindex=reindex)
        return True

    @log_call
    def search(
        self,
        collection_name: str,
        query: str,
        n_results: int = 5,
        *, rank: bool = False, rerank: bool = False, candidate_k: int | None = None,
        embedding_weight: float = 0.8, semantic_dedup_threshold: float | None = None,
    ) -> list[dict]:
        """Search in a specific collection.

        Args:
            collection_name: Name of the collection to search in
            query: Search query string
            n_results: Number of results to return

        Returns:
            List of formatted search results
        """
        collection = self.get_collection(collection_name)
        LOGGER.info("Searching vector store collection '%s'", collection_name)
        return collection.search(query, n_results, rank=rank, rerank=rerank, candidate_k=candidate_k,
                                 embedding_weight=embedding_weight, semantic_dedup_threshold=semantic_dedup_threshold)

    @log_call
    def search_all(
        self,
        query: str,
        n_results: int | None = 5,
        n_results_per_collection: int = 5,
        *, rank: bool = False, rerank: bool = False, candidate_k: int | None = None,
        embedding_weight: float = 0.8, semantic_dedup_threshold: float | None = None,
    ) -> list[dict]:
        """Search across all collections and return globally sorted results.

        Args:
            query: Search query string
            n_results: Global result limit, or None to keep every collected result
            n_results_per_collection: Number of results per collection

        Returns:
            List of results sorted by reciprocal retrieval rank or optional global
            ranking/reranking score, with collection name added
        """
        from platon.vectorstore.chroma_utils import select_search_results

        all_searches = []
        remaining_collections = []
        try:
            if not query.strip() or (n_results is not None and n_results < 1) or n_results_per_collection < 1:
                raise ValueError("Query and result limits must be positive")
            limit = n_results or n_results_per_collection
            candidates = candidate_k if candidate_k is not None else (max(limit, n_results_per_collection, 20) if rank or rerank else n_results_per_collection)
            if candidates < 1 or (candidate_k is not None and candidates < limit):
                raise ValueError("candidate_k must be positive and at least n_results")
            all_coll = self.get_collections()
            remaining_collections = list(all_coll)
            LOGGER.info("Searching %d vector store collection(s)", len(all_coll))

            for name in all_coll:
                collection = self.get_collection(name)
                coll_results = collection.search(query, candidates)

                for position, result in enumerate(coll_results):
                    result["collection"] = name
                    result["retrieval_position"] = position
                    result["retrieval_score"] = 1.0 / (60 + position + 1)
                all_searches.extend(coll_results)
                remaining_collections.remove(name)

            # Distances from collections using different metrics are incomparable.
            # Reciprocal rank provides an explicit metric-independent baseline.
            all_searches.sort(key=lambda x: x["retrieval_score"], reverse=True)
            all_searches = select_search_results(query, all_searches, n_results=n_results or len(all_searches) or 1,
                                                rank=rank, rerank=rerank, embedding_weight=embedding_weight,
                                                semantic_dedup_threshold=semantic_dedup_threshold)

            LOGGER.info("Vector store search completed with %d result(s)", len(all_searches))
            return all_searches

        except Exception as exc:
            LOGGER.error("Vector store search across collections failed (exception=%s)", type(exc).__name__)
            raise VectorStoreError(
                "searching all collections", exc, partial_results=all_searches,
                remaining_collections=remaining_collections,
            ) from exc
