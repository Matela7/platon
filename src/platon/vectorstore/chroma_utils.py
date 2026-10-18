import os
import uuid
import chromadb

from typing import Any, Sequence
from langchain_text_splitters import RecursiveCharacterTextSplitter

from pypdf import PdfReader
from docx import Document
from platon.embedding_models import get_embedding_model, get_reranking_model
from platon.websearch.utils import cosine_similarity
from platon.app_logging import LOGGER, log_call

@log_call
def get_model():
    """Get the process-wide, thread-safe embedding model."""
    return get_embedding_model()

def get_text_splitter(chunk_size: int = 1000, chunk_overlap: int = 100) -> RecursiveCharacterTextSplitter:
    """Create a character-based splitter with validated ingestion settings."""
    if chunk_size < 1 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("Require chunk_size > 0 and 0 <= chunk_overlap < chunk_size")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
    return text_splitter

@log_call
def load_pdf_pages_document(file_path: str) ->list:
    """Load a PDF document and extract text from each page."""
    reader = PdfReader(file_path)
    pages = []

    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            pages.append((i, text))

    LOGGER.info("PDF text extraction finished (pages_with_text=%d)", len(pages))
    return pages

@log_call
def load_docx_paragraphs_document(file_path: str) -> list:
    """Load text from a DOCX document."""
    doc = Document(file_path)
    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
    LOGGER.info("DOCX text extraction finished (paragraphs=%d)", len(doc.paragraphs))
    return text   

@log_call
def add_docx_document_to_vector_store(collection, docx_text: str, doc_name: str | None = None, chunk_size: int = 1000, chunk_overlap: int = 100, source_metadata: dict | None = None) -> None:
    """Add DOCX document to the vector store."""
    text_splitter = get_text_splitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    model = get_model()
    chunks = text_splitter.split_text(docx_text)
    LOGGER.info("Embedding DOCX chunks (count=%d)", len(chunks))
    
    embeddings = model.encode(chunks).tolist()
    ids = [str(uuid.uuid4()) for _ in chunks]
    
    metadatas = [
        {"name": doc_name or "unknown_docx", "chunk_id": i, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap, **(source_metadata or {})}
        for i in range(len(chunks))
    ]
    
    collection.add(
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )
    LOGGER.info("DOCX chunks added to vector store (count=%d)", len(chunks))

@log_call
def add_pdf_document_to_vector_store(collection, pdf_pages: list[str], doc_name: str | None = None, chunk_size: int = 1000, chunk_overlap: int = 100, source_metadata: dict | None = None) -> None:
    """Add PDF pages to the vector store."""
    text_splitter = get_text_splitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    model = get_model()
    total_chunks = 0
    for page_num, page_text in pdf_pages:
        chunks = text_splitter.split_text(page_text)
        total_chunks += len(chunks)

        if not chunks:
            continue
        embeddings = model.encode(chunks).tolist()
        ids = [str(uuid.uuid4()) for _ in chunks]

        metadatas = [
            {"name": doc_name or "unknown_pdf", "page": page_num,
             "page_number": page_num + 1, "chunk_id": i, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap, **(source_metadata or {})}
            for i in range(len(chunks))
        ]

        collection.add(
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
    LOGGER.info("PDF chunks added to vector store (count=%d)", total_chunks)

@log_call
def load_document(file_path: str) -> str:
    """Load a document from a file."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()
    
@log_call
def add_document_to_vector_store(collection, document: str, doc_name: str, chunk_size: int = 1000, chunk_overlap: int = 100, source_metadata: dict | None = None) -> None:
    text_splitter = get_text_splitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    model = get_model()
    chunks = text_splitter.split_text(document)
    LOGGER.info("Embedding text document chunks (count=%d)", len(chunks))

    embeddings = model.encode(chunks).tolist()
    ids = [str(uuid.uuid4()) for _ in chunks]

    metadatas = [
        {"name": doc_name, "chunk_id": i, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap, **(source_metadata or {})}
        for i in range(len(chunks))
    ]

    collection.add(
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )
    LOGGER.info("Text document chunks added to vector store (count=%d)", len(chunks))

@log_call
def similarity_search(collection, query: str, top_k: int = 5):
    """Perform a similarity search in the vector store."""
    query_embedding = get_model().encode(query).tolist()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    count = len(results.get("documents", [[]])[0] or [])
    LOGGER.info("Vector similarity search returned %d result(s)", count)
    return results

def format_search_results(results: dict) -> list[dict]:
    """Format similarity search results for easier consumption."""
    formatted = []
    if not results["documents"] or not results["documents"][0]:
        return formatted
    
    for doc, metadata, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        metadata = dict(metadata or {})
        # Older collections only have the zero-based PDF page index.
        if "page_number" not in metadata and isinstance(metadata.get("page"), int):
            metadata["page_number"] = metadata["page"] + 1
        formatted.append({
            "document": doc,
            "metadata": metadata,
            "distance": distance,
            "similarity": 1 - distance  # Legacy value; not a calibrated score.
        })
    
    return formatted

@log_call
def start_chromadb(persist_dir: str = "./chroma_data") -> chromadb.PersistentClient:
    if not os.path.exists(persist_dir):
        os.makedirs(persist_dir)

    client = chromadb.PersistentClient(path=persist_dir)
    LOGGER.info("ChromaDB client started with persistence directory: %s", persist_dir)
    return client

@log_call
def get_collection(client, name: str):
    LOGGER.info("Retrieving or creating collection '%s'", name)
    return client.get_or_create_collection(name=name)

def _provenance_key(result: dict[str, Any]) -> tuple:
    metadata = result.get("metadata") or {}
    return (result.get("collection"), metadata.get("source_path") or metadata.get("name"),
            metadata.get("page_number", metadata.get("page")))


def _deduplicate_exact(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate passages only when their source provenance also matches."""
    seen = set()
    unique = []
    for result in results:
        key = (result.get("document", ""), *_provenance_key(result))
        if key not in seen:
            seen.add(key)
            unique.append(result)
    return unique


@log_call
def _rank_results(
    query: str,
    results: list[dict[str, Any]],
    *,
    top_k: int = 5,
    embedding_weight: float = 0.8,
    semantic_dedup_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Rank passages using query cosine similarity and reciprocal retrieval rank.

    Semantic deduplication is opt-in and only merges passages from the same
    source and page, so evidence from different documents remains available.
    """
    if not 0.0 <= embedding_weight <= 1.0:
        raise ValueError("embedding_weight must be between 0 and 1")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    if semantic_dedup_threshold is not None and not 0 <= semantic_dedup_threshold <= 1:
        raise ValueError("semantic_dedup_threshold must be between 0 and 1")
    unique = _deduplicate_exact(results)
    if not unique:
        return []
    vectors = get_embedding_model().encode(
        [query] + [result["document"] for result in unique], normalize_embeddings=True
    )
    ranked = []
    for index, (result, vector) in enumerate(zip(unique, vectors[1:], strict=True)):
        similarity = cosine_similarity(vectors[0], vector)
        position = int(result.get("retrieval_position", index))
        retrieval_score = 1.0 / (position + 1)
        ranked.append({**result, "similarity_score": similarity,
                       "retrieval_score": retrieval_score,
                       "final_score": embedding_weight * similarity + (1 - embedding_weight) * retrieval_score,
                       "_vector": vector})
    ranked.sort(key=lambda item: item["final_score"], reverse=True)
    selected = []
    for result in ranked:
        if semantic_dedup_threshold is not None:
            same_passage = any(
                _provenance_key(result) == _provenance_key(other)
                and cosine_similarity(result["_vector"], other["_vector"]) >= semantic_dedup_threshold
                for other in selected
            )
            if same_passage:
                continue
        selected.append(result)
        if len(selected) >= top_k:
            break
    return [{key: value for key, value in {**item, "rank": rank}.items() if key != "_vector"}
            for rank, item in enumerate(selected, 1)]


def rerank_results(query: str, results: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Score query/passage pairs with an optional multilingual CrossEncoder."""
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    unique = _deduplicate_exact(results)
    if not unique:
        return []
    scores = get_reranking_model().predict([(query, item["document"]) for item in unique])
    ranked = [{**item, "rerank_score": float(score)} for item, score in zip(unique, scores, strict=True)]
    ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
    return [{**item, "rank": index} for index, item in enumerate(ranked[:top_k], 1)]


def select_search_results(query: str, results: list[dict], *, n_results: int,
                          rank: bool = False, rerank: bool = False,
                          embedding_weight: float = 0.8,
                          semantic_dedup_threshold: float | None = None) -> list[dict]:
    """Apply optional stages to the full candidate pool before final truncation."""
    if rank:
        results = _rank_results(query, results, top_k=max(1, len(results)),
                               embedding_weight=embedding_weight,
                               semantic_dedup_threshold=semantic_dedup_threshold)
    if rerank:
        return rerank_results(query, results, n_results)
    return results[:n_results]

## test

if __name__ == "__main__":
    client = start_chromadb()
    collection = get_collection(client, "debug1_collection")

    # # Load and add a sample document to a real collection object.
    # sample_text = "This is a sample document for testing the Chroma vector store."
    # add_document_to_vector_store(collection, sample_text, "sample_doc.txt")

    # # Perform a similarity search
    # query = "Barack Obama"
    # results = similarity_search(collection, query)
    # print(results)

    path_to_pdf = "C:\\Users\\miche\\platon\\data\\documents\\PODSTAWY-ANARTOMII-I-FIZJOLOGII-.pdf"
    document = load_pdf_pages_document(path_to_pdf)
    add_pdf_document_to_vector_store(collection, document, "pdf_test_1.pdf")

    print("PDF document added to vector store.")

    query = "miÄ™Ĺ›nie skoĹ›ne brzucha"
    results = similarity_search(collection, query)
    print(results)
