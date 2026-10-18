import hashlib
import json
import uuid
from pathlib import Path

from chromadb.errors import NotFoundError

from platon.embedding_models import DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_REVISION
from platon.vectorstore.chroma_utils import (
    load_pdf_pages_document,
    load_docx_paragraphs_document,
    load_document,
    add_pdf_document_to_vector_store,
    add_docx_document_to_vector_store,
    add_document_to_vector_store,
    similarity_search,
    select_search_results,
    format_search_results
)
from platon.vectorstore.errors import VectorStoreError

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
    
    def info(self) -> dict:
        """Return persisted ingestion settings without loading document contents."""
        try:
            collection = self._get_collection()
            metadata = collection.metadata if isinstance(collection.metadata, dict) else {}
            return {"name": self.name, "count": collection.count(),
                    "metadata": metadata,
                    "documents": json.loads(metadata.get("platon_ingestions", "{}"))}
        except Exception as exc:
            raise VectorStoreError("reading collection info", exc, collection=self.name) from exc

    def add_document(self, file_path: str, doc_name: str, chunk_size: int = 1000,
                     chunk_overlap: int = 100, reindex: bool = False) -> None:
        """Reuse unchanged sources; require explicit reindex for modified settings/content.

        Completion manifests are persisted only after every chunk was written.
        Old chunks are deleted only after replacement chunks were added successfully.
        """
        try:
            if chunk_size < 1 or not 0 <= chunk_overlap < chunk_size:
                raise ValueError("Require chunk_size > 0 and 0 <= chunk_overlap < chunk_size")
            path = Path(file_path).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"File not found: {file_path}")
            if path.suffix.lower() not in {".pdf", ".docx", ".txt"}:
                raise ValueError(f"Unsupported file format: {path.suffix}")
            source_id = hashlib.sha256(str(path).encode()).hexdigest()
            with path.open("rb") as source:
                fingerprint = hashlib.file_digest(source, "sha256").hexdigest()
            expected = {"source_path": str(path), "source_sha256": fingerprint,
                        "name": doc_name, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap,
                        "splitter": "RecursiveCharacterTextSplitter", "length_unit": "characters",
                        "embedding_model": DEFAULT_EMBEDDING_MODEL,
                        "embedding_revision": DEFAULT_EMBEDDING_REVISION}
            try:
                collection = self._get_collection()
            except NotFoundError:
                collection = None
            metadata = collection.metadata if collection is not None and isinstance(collection.metadata, dict) else {}
            manifests = json.loads(metadata.get("platon_ingestions", "{}"))
            previous = manifests.get(source_id)
            if previous and all(previous.get(key) == value for key, value in expected.items()) and not reindex:
                return
            if previous and not reindex:
                raise ValueError("Source or ingestion settings changed; inspect get_collection_info and use reindex=True to replace its chunks")
            old_ids = []
            if collection is not None:
                existing = collection.get(where={"$or": [{"source_id": source_id}, {"name": doc_name}]}, include=["metadatas"])
                if isinstance(existing, dict):
                    for identifier, item in zip(existing.get("ids", []), existing.get("metadatas", [])):
                        item = item or {}
                        if item.get("source_id") == source_id or not item.get("source_id"):
                            old_ids.append(identifier)
                if old_ids and not reindex:
                    raise ValueError("Existing chunks have no matching completion manifest; use search first or reindex=True to replace legacy/incomplete ingestion")
            match path.suffix.lower():
                case '.pdf':
                    document = load_pdf_pages_document(str(path))
                    if not any(text.strip() for _, text in document):
                        raise ValueError("PDF contains no extractable text")
                    writer = add_pdf_document_to_vector_store
                case '.docx':
                    document = load_docx_paragraphs_document(str(path))
                    if not document.strip():
                        raise ValueError("DOCX contains no text")
                    writer = add_docx_document_to_vector_store
                case _:
                    document = load_document(str(path))
                    if not document.strip():
                        raise ValueError("Document contains no text")
                    writer = add_document_to_vector_store
            if collection is None:
                collection = self._get_collection(create=True)
            ingestion_id = uuid.uuid4().hex
            source_metadata = {**expected, "source_id": source_id, "ingestion_id": ingestion_id}
            try:
                writer(collection, document, doc_name, chunk_size=chunk_size,
                       chunk_overlap=chunk_overlap, source_metadata=source_metadata)
            except Exception:
                try:
                    collection.delete(where={"ingestion_id": ingestion_id})
                except Exception:
                    # Preserve the original failure; explicit reindex can clean up.
                    pass
                raise
            if old_ids:
                collection.delete(ids=old_ids)
            manifests[source_id] = {**expected, "ingestion_id": ingestion_id}
            # Chroma modify replaces metadata, so preserve unrelated entries.
            collection.modify(metadata={**metadata, "platon_ingestions": json.dumps(manifests)})
        except Exception as exc:
            raise VectorStoreError("adding document", exc, collection=self.name,
                                   document=doc_name) from exc

    def search(self, query: str, n_results: int = 5, *, rank: bool = False,
               rerank: bool = False, candidate_k: int | None = None,
               embedding_weight: float = 0.8, semantic_dedup_threshold: float | None = None) -> list[dict]:
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
            candidates = candidate_k if candidate_k is not None else (max(n_results, 20) if rank or rerank else n_results)
            if candidates < n_results:
                raise ValueError("candidate_k must be at least n_results")
            raw_results = similarity_search(self._get_collection(), query, candidates)
            return select_search_results(query, format_search_results(raw_results), n_results=n_results,
                                         rank=rank, rerank=rerank, embedding_weight=embedding_weight,
                                         semantic_dedup_threshold=semantic_dedup_threshold)
        except Exception as exc:
            raise VectorStoreError("searching collection", exc, collection=self.name) from exc
