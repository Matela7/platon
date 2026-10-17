from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app_logging import LOGGER, log_call
if TYPE_CHECKING:
    from vectorstore.collection_store import CollectionStore


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
            from vectorstore.chroma_utils import start_chromadb

            self._client = start_chromadb(self.persist_dir)
        return self._client

    def get_collection(self, name: str) -> CollectionStore:
        """Get or create a collection."""
        from vectorstore.collection_store import CollectionStore

        return CollectionStore(self.client, name)

    def get_collections(self) -> list[str]:
        """List all collection names."""
        return [coll.name for coll in self.client.list_collections()]

    @log_call
    def add_document_to_collection(
        self,
        collection_name: str,
        file_path: str,
        doc_name: str,
    ) -> bool:
        """Add a document to a specific collection.

        Returns True if the document was added successfully, False otherwise.
        """
        collection = self.get_collection(collection_name)
        LOGGER.info("Ingesting document into collection '%s'", collection_name)
        collection.add_document(file_path, doc_name)
        return True

    @log_call
    def search(
        self,
        collection_name: str,
        query: str,
        n_results: int = 5,
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
        return collection.search(query, n_results)

    @log_call
    def search_all(
        self,
        query: str,
        n_results: int | None = 5,
        n_results_per_collection: int = 5,
    ) -> list[dict]:
        """Search across all collections and return globally sorted results.

        Args:
            query: Search query string
            n_results: Global result limit, or None to keep every collected result
            n_results_per_collection: Number of results per collection

        Returns:
            List of results sorted by similarity (highest first), with collection name added
        """
        all_searches = []
        remaining_collections = []
        try:
            all_coll = self.client.list_collections()
            remaining_collections = [coll.name for coll in all_coll]
            LOGGER.info("Searching %d vector store collection(s)", len(all_coll))

            for coll in all_coll:
                collection = self.get_collection(coll.name)
                coll_results = collection.search(query, n_results_per_collection)

                for result in coll_results:
                    result["collection"] = coll.name
                all_searches.extend(coll_results)
                remaining_collections.remove(coll.name)

            all_searches.sort(key=lambda x: x["similarity"], reverse=True)

            if n_results is not None:
                all_searches = all_searches[:n_results]

            LOGGER.info("Vector store search completed with %d result(s)", len(all_searches))
            return all_searches

        except Exception as exc:
            LOGGER.error("Vector store search across collections failed (exception=%s)", type(exc).__name__)
            error = RuntimeError(f"Error searching collections {remaining_collections}: {exc}")
            error.partial_results = all_searches
            error.remaining_collections = remaining_collections
            raise error from exc
