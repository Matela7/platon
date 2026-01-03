from chroma_utils import (
    load_pdf_pages_document,
    load_docx_paragraphs_document,
    load_document,
    add_pdf_document_to_vector_store,
    add_docx_document_to_vector_store,
    add_document_to_vector_store,
    similarity_search,
    format_search_results
)
import os

class CollectionStore:
    def __init__(self, client, name: str):
        self.client = client
        self.name = name
        self._collection = None

    @property
    def _get_collection(self):
        """Get or create the collection (internal use)."""
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(name=self.name)
        return self._collection
    
    def _save_uploaded_file(self, file_path: str, content: bytes) -> str:
        target_dir = os.path.join("data", self.name)
        os.makedirs(target_dir, exist_ok=True)

        filename = os.path.basename(file_path)
        target_path = os.path.join(target_dir, filename)

        with open(target_path, "wb") as f:
            f.write(content)

        return target_path    
    
    def add_document(self, file_path: str, doc_name: str) -> None:
        """Add a document to the collection based on file format."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        document_prefix = file_path.split('.')[-1].lower()
        
        try:
            match document_prefix:
                case 'pdf':
                    document = load_pdf_pages_document(file_path)
                    add_pdf_document_to_vector_store(self._get_collection, document, doc_name)
                case 'docx':
                    document = load_docx_paragraphs_document(file_path)
                    add_docx_document_to_vector_store(self._get_collection, document, doc_name)
                case 'txt':
                    document = load_document(file_path)
                    add_document_to_vector_store(self._get_collection, document, doc_name)
                case _:
                    raise ValueError(f"Unsupported file format: {document_prefix}")
        except Exception as e:
            raise RuntimeError(f"Error adding document '{doc_name}': {str(e)}")
    
    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """Search documents in the collection.
        
        Args:
            query: Search query string
            n_results: Number of results to return
            
        Returns:
            List of formatted search results with documents, metadata, and similarity scores
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")
        
        raw_results = similarity_search(self._get_collection, query, n_results)
        return format_search_results(raw_results) 