from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from langchain_core.tools import BaseTool, tool
from pydantic import Field

from platon.agent.tools.common import configure_error_handling, truncate_output
from platon.agent.tools.errors import ToolError
from platon.app_logging import log_call

if TYPE_CHECKING:
    from platon.vectorstore.client_manager import ClientManager


def create_rag_tools(cm: ClientManager, max_output_chars: int = 20_000) -> tuple[BaseTool, ...]:
    """Create tools backed by the private vector-store client."""

    def bounded_results(results):
        if not results:
            return results
        allowance = max(1, max_output_chars // len(results))
        return [{**item, "document": truncate_output(item["document"], allowance)}
                if isinstance(item, dict) and "document" in item else item for item in results]

    @tool
    @log_call
    def search_collection(collection_name: str, query: str, n_results: Annotated[int, Field(ge=1, le=50)] = 5) -> list:
        """Search a specific collection using the ClientManager."""
        try:
            return bounded_results(cm.search(collection_name, query, n_results))
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
    ) -> list:
        """Search all collections using the ClientManager."""
        try:
            return bounded_results(cm.search_all(query, n_results, n_results_per_collection))
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
    def add_document_to_collection(collection_name: str, file_path: str, doc_name: str) -> bool:
        """Add a document to a specific collection."""
        try:
            return cm.add_document_to_collection(collection_name, file_path, doc_name)
        except Exception as exc:
            raise ToolError.from_exception(
                "add_document_to_collection",
                f"adding document '{doc_name}' to collection '{collection_name}'",
                exc,
            ) from exc

    return tuple(
        configure_error_handling(tool_instance)
        for tool_instance in (
            search_collection,
            search_all_collections,
            get_list_of_collections,
            add_document_to_collection,
        )
    )
