from platon.vectorstore.chroma_utils import (
    load_pdf_pages_document,
    load_docx_paragraphs_document,
    load_document,
    add_pdf_document_to_vector_store,
    add_docx_document_to_vector_store,
    add_document_to_vector_store,
    similarity_search,
    format_search_results
)
from platon.vectorstore.errors import VectorStoreError
from pathlib import Path

class CollectionStore:
    def __init__(self, client, name: str):
        self.client = client
        self.name = name
        self._collection = None

    def _get_collection(self, *, create: bool = False):
        """Only ingestion may create a collection; retrieval reports missing names."""
        if self._collection is None:
            getter = self.client.get_or_create_collection if create else self.client.get_collection
            self._collection = getter(name=self.name)
        return self._collection
    
    def _save_uploaded_file(self, file_path: str, content: bytes) -> str:
        target_dir = Path("data") / self.name
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = Path(file_path).name
        target_path = target_dir / filename

        with open(target_path, "wb") as f:
            f.write(content)

        return target_path    
    
    def add_document(self, file_path: str, doc_name: str) -> None:
        """Add a document to the collection based on file format."""
        try:
            path = Path(file_path)
            if not path.is_file():
                raise FileNotFoundError(f"File not found: {file_path}")
            document_prefix = path.suffix.lstrip(".").lower()
            match document_prefix:
                case 'pdf':
                    document = load_pdf_pages_document(file_path)
                    if not any(text.strip() for _, text in document):
                        raise ValueError("PDF contains no extractable text")
                    add_pdf_document_to_vector_store(self._get_collection(create=True), document, doc_name)
                case 'docx':
                    document = load_docx_paragraphs_document(file_path)
                    if not document.strip():
                        raise ValueError("DOCX contains no text")
                    add_docx_document_to_vector_store(self._get_collection(create=True), document, doc_name)
                case 'txt':
                    document = load_document(file_path)
                    if not document.strip():
                        raise ValueError("Document contains no text")
                    add_document_to_vector_store(self._get_collection(create=True), document, doc_name)
                case _:
                    raise ValueError(f"Unsupported file format: {document_prefix}")
        except Exception as exc:
            raise VectorStoreError("adding document", exc, collection=self.name,
                                   document=doc_name) from exc
    
    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """Search documents in the collection.
        
        Args:
            query: Search query string
            n_results: Number of results to return
            
        Returns:
            List of formatted search results with documents, metadata, and similarity scores
        """
        try:
            if not query or not query.strip():
                raise ValueError("Query cannot be empty")
            if n_results < 1:
                raise ValueError("n_results must be positive")
            raw_results = similarity_search(self._get_collection(), query, n_results)
            return format_search_results(raw_results)
        except Exception as exc:
            raise VectorStoreError("searching collection", exc, collection=self.name) from exc
