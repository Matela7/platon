from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_community.utilities import SerpAPIWrapper

from client_manager import ClientManager
from collection_store import CollectionStore
def create_search_tools(cm: ClientManager):
    @tool
    def search_collection(collection_name: str, query: str, n_results: int = 5) -> list:
        """Search a specific collection using the ClientManager."""
        return cm.search(collection_name, query, n_results)

    @tool
    def search_all_collections(query: str, n_results: int = 5, n_results_per_collection: int = 5) -> list:
        """Search all collections using the ClientManager."""
        return cm.search_all(query, n_results, n_results_per_collection)

    def get_searchapi_tool() -> SerpAPIWrapper:
        """Initialize and return the SerpAPI search tool."""
        return SerpAPIWrapper()
    
    return search_collection, search_all_collections, get_searchapi_tool
# @tool
# def search_collection(collection_name: str, cm: ClientManager, query: str, n_results: int = 5) -> list:
#     """Search a specific collection using the ClientManager."""
#     return cm.search(collection_name, query, n_results)

# @tool
# def search_all_collections(cm: ClientManager, query: str, n_results: int = 5, n_results_per_collection: int = 5) -> list:
#     """Search all collections using the ClientManager."""
#     return cm.search_all(query, n_results, n_results_per_collection)

# def get_searchapi_tool() -> SerpAPIWrapper:
#     """Initialize and return the SerpAPI search tool."""
#     return SerpAPIWrapper()
