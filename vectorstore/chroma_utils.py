import os
import uuid
import chromadb
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter

from pypdf import PdfReader
from docx import Document

model = SentenceTransformer("all-MiniLM-L6-v2")
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100
)

def get_model():
    """Get the global SentenceTransformer model."""
    return model

def get_text_splitter():
    """Get the global text splitter."""
    return text_splitter

def load_pdf_pages_document(file_path: str) ->list:
    """Load a PDF document and extract text from each page."""
    reader = PdfReader(file_path)
    pages = []

    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            pages.append((i, text))

    return pages

def load_docx_paragraphs_document(file_path: str) -> list:
    """Load text from a DOCX document."""
    doc = Document(file_path)
    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
    return text   

def add_docx_document_to_vector_store(collection, docx_text: str, doc_name: str | None = None) -> None:
    """Add DOCX document to the vector store."""
    chunks = text_splitter.split_text(docx_text)
    
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

def add_pdf_document_to_vector_store(collection, pdf_pages: list[str], doc_name: str | None = None) -> None:
    """Add PDF pages to the vector store."""
    for page_num, page_text in pdf_pages:
        chunks = text_splitter.split_text(page_text)

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

def load_document(file_path: str) -> str:
    """Load a document from a file."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()
    
def add_document_to_vector_store(collection, document: str, doc_name: str) -> None:
    chunks = text_splitter.split_text(document)

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

def similarity_search(collection, query: str, top_k: int = 5):
    """Perform a similarity search in the vector store."""
    query_embedding = get_model().encode(query).tolist()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
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

def start_chromadb(persist_dir: str = "./chroma_data") -> chromadb.PersistentClient:
    if not os.path.exists(persist_dir):
        os.makedirs(persist_dir)

    client = chromadb.PersistentClient(path=persist_dir)
    return client

def get_collection(client, name: str):
    return client.get_or_create_collection(name=name)


## test

if __name__ == "__main__":
    collection = start_chromadb()

    # Load and add a sample document
    sample_text = "This is a sample document for testing the Chroma vector store."
    add_document_to_vector_store(collection, sample_text, "sample_doc.txt")
    sample_pdf = load_pdf_pages_document("duda.pdf")
    add_pdf_document_to_vector_store(collection, sample_pdf, "dudadupa")
    # Perform a similarity search
    query = "Barack Obama"
    results = similarity_search(collection, query)
    print(results)