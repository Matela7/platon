"""Vector-store failures with operation context and preserved causes."""

class VectorStoreError(RuntimeError):
    def __init__(self, operation: str, cause: Exception, *, collection: str | None = None,
                 document: str | None = None, partial_results: list | None = None,
                 remaining_collections: list[str] | None = None) -> None:
        self.operation = operation
        self.collection = collection
        self.document = document
        self.partial_results = partial_results or []
        self.remaining_collections = remaining_collections or []
        self.category = None
        # Import Chroma only on the database error path, not at application startup.
        from chromadb.errors import ChromaError
        if isinstance(cause, ChromaError):
            code = cause.code()
            self.category = ("lookup" if code == 404 else
                             "permission" if code in {401, 403} else
                             "transient" if code == 429 or code >= 500 else "validation")
        context = f" in collection {collection!r}" if collection else ""
        context += f" for document {document!r}" if document else ""
        super().__init__(f"Vector store failed while {operation}{context}: {type(cause).__name__}: {cause}")
