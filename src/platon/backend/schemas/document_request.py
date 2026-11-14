"""Document metadata exposed by the backend."""

from pydantic import BaseModel


class DocumentRecord(BaseModel):
    """Identify a stored document and its Chroma collection.

    Attributes:
        id: Unique document identifier.
        filename: Original document name.
        path: Absolute path to the stored file.
        collection: Chroma collection containing the document.
    """

    id: str
    filename: str
    path: str
    collection: str
