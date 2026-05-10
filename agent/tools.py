from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_community.utilities import SerpAPIWrapper
from langchain_community.tools import ShellTool

from vectorstore.client_manager import ClientManager
from vectorstore.collection_store import CollectionStore
from pathlib import Path
from datetime import datetime

def create_search_tools(cm: ClientManager) -> tuple:
    @tool
    def search_collection(collection_name: str, query: str, n_results: int = 5) -> list:
        """Search a specific collection using the ClientManager."""
        return cm.search(collection_name, query, n_results)

    @tool
    def search_all_collections(query: str, n_results: int = 5, n_results_per_collection: int = 5) -> list:
        """Search all collections using the ClientManager."""
        return cm.search_all(query, n_results, n_results_per_collection)
    @tool
    def get_list_of_collections() -> list[str]:
        """Get a list of all collection names."""
        return cm.get_collections()
    @tool
    def add_document_to_collection(collection_name: str, file_path: str, doc_name: str) -> bool:
        """Add a document to a specific collection."""
        return cm.add_document_to_collection(collection_name, file_path, doc_name)
    @tool
    def search_web(query: str) -> str:
        """Search the web for recent information using SerpAPI."""
        return SerpAPIWrapper().run(query)

    return (search_collection, search_all_collections, search_web, get_list_of_collections,
            add_document_to_collection)

def create_utils_tools() -> tuple:
    @tool
    def get_current_time() -> str:
        """Get the current date and time in ISO 8601 format."""
        return datetime.now().isoformat()
    
    @tool
    def get_system_path() -> str:
        """Get the current working directory path."""
        return str(Path.cwd())

    @tool
    def execute_ls_command(path: str) -> str:
        """Execute the 'ls' command on a specified path."""
        return ShellTool().run(f"ls {path}")
    
    return (get_current_time, get_system_path, execute_ls_command)
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
