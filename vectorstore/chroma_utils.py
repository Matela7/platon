import os
import uuid
import chromadb

from langchain_text_splitters import RecursiveCharacterTextSplitter

from pypdf import PdfReader
from docx import Document
from ..embedding_models import get_embedding_model
from app_logging import LOGGER, log_call

@log_call
def get_model():
    """Get the process-wide, thread-safe embedding model."""
    return get_embedding_model()

def get_text_splitter():
    """Get the global text splitter."""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100
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
def add_docx_document_to_vector_store(collection, docx_text: str, doc_name: str | None = None) -> None:
    """Add DOCX document to the vector store."""
    text_splitter = get_text_splitter()
    model = get_model()
    chunks = text_splitter.split_text(docx_text)
    LOGGER.info("Embedding DOCX chunks (count=%d)", len(chunks))
    
    embeddings = model.encode(chunks).tolist()
    ids = [str(uuid.uuid4()) for _ in chunks]
    
    metadatas = [
        {"name": doc_name or "unknown_docx", "chunk_id": i}
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
def add_pdf_document_to_vector_store(collection, pdf_pages: list[str], doc_name: str | None = None) -> None:
    """Add PDF pages to the vector store."""
    text_splitter = get_text_splitter()
    model = get_model()
    total_chunks = 0
    for page_num, page_text in pdf_pages:
        chunks = text_splitter.split_text(page_text)
        total_chunks += len(chunks)

        embeddings = model.encode(chunks).tolist()
        ids = [str(uuid.uuid4()) for _ in chunks]

        metadatas = [
            {"name": doc_name or "unknown_pdf", "page": page_num, "chunk_id": i}
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
def add_document_to_vector_store(collection, document: str, doc_name: str) -> None:
    text_splitter = get_text_splitter()
    model = get_model()
    chunks = text_splitter.split_text(document)
    LOGGER.info("Embedding text document chunks (count=%d)", len(chunks))

    embeddings = model.encode(chunks).tolist()
    ids = [str(uuid.uuid4()) for _ in chunks]

    metadatas = [
        {"name": doc_name, "chunk_id": i}
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
        formatted.append({
            "document": doc,
            "metadata": metadata,
            "distance": distance,
            "similarity": 1 - distance  # Convert distance to similarity score
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


## test

if __name__ == "__main__":
    client = start_chromadb()
    collection = get_collection(client, "debug_collection")

    # Load and add a sample document to a real collection object.
    sample_text = "This is a sample document for testing the Chroma vector store."
    add_document_to_vector_store(collection, sample_text, "sample_doc.txt")

    if os.path.exists("C:\\Users\\miche\\platon\\agent\\PODSTAWY-ANARTOMII-I-FIZJOLOGII-.pdf"):
        sample_pdf = load_pdf_pages_document("C:\\Users\\miche\\platon\\agent\\PODSTAWY-ANARTOMII-I-FIZJOLOGII-.pdf")
        add_pdf_document_to_vector_store(collection, sample_pdf, "PODSTAWY.pdf")

    # Perform a similarity search
    query = "Barack Obama"
    results = similarity_search(collection, query)
    print(results)
