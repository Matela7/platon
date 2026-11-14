"""API for uploading, listing and deleting documents."""

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from platon.app_logging import LOGGER
from platon.backend.services.document_service import MAX_UPLOAD_BYTES
from platon.vectorstore.errors import VectorStoreError

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("", status_code=201)
async def upload_document(request: Request, filename: str = Query(min_length=1, max_length=255), collection: str = "documents"):
    """Upload a document and index it in the selected collection."""
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Document exceeds 100 MiB")
        content.extend(chunk)
    try:
        return {"data": await run_in_threadpool(request.app.state.document_service.upload, filename, bytes(content), collection)}
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, f"Uploading document failed: {exc}") from exc
    except VectorStoreError as exc:
        LOGGER.exception("Document indexing failed")
        status = 422 if isinstance(exc.__cause__, (ValueError, UnicodeError)) else 503
        raise HTTPException(status, f"Uploading document failed: {exc}") from exc
    except Exception as exc:
        LOGGER.exception("Document upload failed")
        raise HTTPException(500, f"Uploading document failed: {exc}") from exc


@router.get("")
def list_documents(request: Request, collection: str | None = None):
    """List stored documents, optionally filtering by collection."""
    try:
        return {"data": request.app.state.document_service.list_documents(collection)}
    except ValueError as exc:
        raise HTTPException(422, f"Listing documents failed: {exc}") from exc
    except Exception as exc:
        LOGGER.exception("Listing documents failed")
        raise HTTPException(500, f"Listing documents failed: {exc}") from exc


@router.delete("/{document_id}")
def delete_document(document_id: str, request: Request):
    """Remove a document from the catalogue, disk, and Chroma."""
    try:
        return {"data": request.app.state.document_service.delete(document_id)}
    except ValueError as exc:
        raise HTTPException(422, f"Deleting document failed: {exc}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, f"Deleting document failed: {exc}") from exc
    except Exception as exc:
        LOGGER.exception("Deleting document failed")
        raise HTTPException(500, f"Deleting document failed: {exc}") from exc
