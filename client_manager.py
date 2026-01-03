from chroma_utils import start_chromadb
from collection_store import CollectionStore

class ClientManager:
    def __init__(self, persist_dir: str = "./chroma_data"):
        self.client = start_chromadb(persist_dir)

    def get_collection(self, name: str) -> CollectionStore:
        """Get or create a collection."""
        return CollectionStore(self.client, name)
    
    def search(self, collection_name: str, query: str, n_results: int = 5) -> list[dict]:
        """Search in a specific collection.
        
        Args:
            collection_name: Name of the collection to search in
            query: Search query string
            n_results: Number of results to return
            
        Returns:
            List of formatted search results
        """
        collection = self.get_collection(collection_name)
        return collection.search(query, n_results)
    
    def search_all(self, query: str, n_results: int = 5, n_results_per_collection: int = 5) -> list[dict]:
        """Search across all collections and return globally sorted results.
        
        Args:
            query: Search query string
            n_results: Global limit of results to return (optional, uses per-collection limit if None)
            n_results_per_collection: Number of results per collection
            
        Returns:
            List of results sorted by similarity (highest first), with collection name added
        """
        try:
            all_coll = self.client.list_collections()
            all_searches = []

            for coll in all_coll:
                collection = self.get_collection(coll.name)
                coll_results = collection.search(query, n_results_per_collection)

                for result in coll_results:
                    result["collection"] = coll.name
                all_searches.extend(coll_results) 
            
            all_searches.sort(key=lambda x: x["similarity"], reverse=True)
            
            if n_results is not None:
                all_searches = all_searches[:n_results]
            
            return all_searches

        except Exception as e:
            raise RuntimeError(f"Error searching all collections: {str(e)}")
