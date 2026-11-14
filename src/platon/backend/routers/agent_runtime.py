"""HTTP endpoints calling AgentRuntimeService directly."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from platon.app_logging import LOGGER, log_call
from platon.backend.schemas.initialize_runtime import InitializeRuntime
from platon.backend.schemas.message_request import MessageRequest
from platon.backend.utils.image_utils import check_model_multimodal, save_chat_images
from fastapi.responses import FileResponse
from platon.backend.schemas.resume_request import ResumeRequest
from platon.backend.schemas.runtime_config import RuntimeConfig
from platon.backend.utils.agent_runtime import (
    Runtime,
    exclusive_access,
    require_runtime,
    stream_response,
    success,
)

router = APIRouter(prefix="/api/v1/agent-runtime", tags=["agent-runtime"])


@router.post("/initialize")
@log_call
def initialize_runtime(body: InitializeRuntime, request: Request, access=Depends(exclusive_access)):
    service = None
    try:
        service = request.app.state.runtime_factory(
            orchestrator_config=body.orchestrator_config,
            agent_config=body.agent_config,
            thread_id=body.thread_id,
        )
        config = service.get_config()
        thread_id = service.thread_id
    except Exception as exc:
        LOGGER.exception("Agent runtime initialization failed")
        if service is not None:
            try:
                service.close()
            except Exception:
                LOGGER.exception("Failed runtime initialization cleanup")
        raise HTTPException(status_code=500, detail=f"Could not initialize the agent runtime: {exc}") from exc

    previous = request.app.state.agent_runtime
    request.app.state.agent_runtime = service
    if previous is not None:
        try:
            previous.close()
        except Exception:
            LOGGER.exception("Previous runtime cleanup failed")
    return success({"thread_id": thread_id, **config})


@router.get("/snapshot")
@log_call
def get_snapshot(service: Runtime):
    try:
        return success(service.snapshot())
    except Exception as exc:
        LOGGER.exception("Agent runtime snapshot failed")
        raise HTTPException(status_code=500, detail=f"Could not read the runtime snapshot: {exc}") from exc


@router.get("/history")
@log_call
def get_history(service: Runtime):
    try:
        return success(service.history())
    except Exception as exc:
        LOGGER.exception("Agent runtime history failed")
        raise HTTPException(status_code=500, detail=f"Could not read conversation history: {exc}") from exc


@router.get("/threads")
@log_call
def get_threads(service: Runtime):
    try:
        return success(service.list_threads())
    except Exception as exc:
        LOGGER.exception("Agent runtime thread listing failed")
        raise HTTPException(status_code=500, detail=f"Could not list conversations: {exc}") from exc


@router.delete("/threads/{thread_id}")
@log_call
def delete_thread(thread_id: str, service: Runtime):
    if not service.thread_exists(thread_id):
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")
    try:
        deleted = service.delete_thread(thread_id)
        return success({"deleted": deleted, "thread_id": thread_id, "active_thread_id": service.thread_id})
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Agent runtime thread deletion failed (thread_id=%s)", thread_id)
        raise HTTPException(status_code=500, detail=f"Could not delete conversation: {exc}") from exc


@router.delete("/threads")
@log_call
def delete_current_thread(service: Runtime):
    target_id = service.thread_id
    if not service.thread_exists(target_id):
        raise HTTPException(status_code=404, detail=f"Thread not found: {target_id}")
    try:
        deleted = service.delete_thread(target_id)
        return success({"deleted": deleted, "thread_id": target_id, "active_thread_id": service.thread_id})
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Agent runtime current thread deletion failed (thread_id=%s)", target_id)
        raise HTTPException(status_code=500, detail=f"Could not delete conversation: {exc}") from exc


@router.get("/config")
@log_call
def get_config(service: Runtime):
    try:
        return success(service.get_config())
    except Exception as exc:
        LOGGER.exception("Agent runtime configuration read failed")
        raise HTTPException(status_code=500, detail=f"Could not read runtime configuration: {exc}") from exc


@router.put("/config")
@log_call
def replace_config(body: RuntimeConfig, service: Runtime):
    try:
        return success(service.replace_config(body.orchestrator_config, body.agent_config))
    except Exception as exc:
        LOGGER.exception("Agent runtime configuration update failed")
        raise HTTPException(status_code=500, detail=f"Could not update runtime configuration: {exc}") from exc


@router.post("/chat")
@log_call
def chat(body: MessageRequest, request: Request, service: Runtime):
    # Resolve before starting the stream so invalid attachments return an HTTP
    # error and cannot leave a partially recorded conversation turn.
    message = body.message
    if body.document_ids:
        try:
            context = request.app.state.document_service.build_attachment_context(body.document_ids)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            LOGGER.exception("Chat attachment resolution failed")
            raise HTTPException(status_code=503, detail="Could not read chat attachments.") from exc
        message = f"{message}\n\n{context}"
    try:
        return stream_response(service.stream(message))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Agent runtime chat could not start")
        raise HTTPException(status_code=500, detail=f"Could not start chat: {exc}") from exc

@router.post("/chat-with-images")
@log_call
def chat_with_images(
    request: Request,
    service: Runtime,
    message: str = Form(...),
    document_ids: str = Form("[]"),
    images: list[UploadFile] = File(default=[]),
):
    cleaned_message = message.strip()
    if not cleaned_message:
        raise HTTPException(status_code=422, detail="Message cannot be empty.")

    import json as _json
    try:
        parsed_doc_ids = _json.loads(document_ids) if document_ids else []
    except Exception:
        parsed_doc_ids = []

    image_paths: list[str] = []
    if images:
        base_url = service._orchestrator.config.base_url
        model_name = service._orchestrator.agent_config.model_name
        if not check_model_multimodal(base_url, model_name):
            raise HTTPException(
                status_code=422,
                detail=f"Wybrany model ({model_name}) nie obsługuje obrazów. Wybierz model multimodalny w Ustawieniach.",
            )
        backend_root = service._orchestrator.agent_config.backend_root
        saved = save_chat_images(images, backend_root)
        image_paths = [str(p) for p in saved]

    final_message = cleaned_message
    if parsed_doc_ids:
        try:
            context = request.app.state.document_service.build_attachment_context(parsed_doc_ids)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            LOGGER.exception("Chat attachment resolution failed")
            raise HTTPException(status_code=503, detail="Could not read chat attachments.") from exc
        final_message = f"{final_message}\n\n{context}"

    try:
        return stream_response(service.stream(final_message, image_paths=image_paths))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Agent runtime chat with images could not start")
        raise HTTPException(status_code=500, detail=f"Could not start chat: {exc}") from exc



@router.post("/resume")
@log_call
def resume(body: ResumeRequest, service: Runtime):
    try:
        return stream_response(service.resume_stream(body.decisions))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Agent runtime resume could not start")
        raise HTTPException(status_code=500, detail=f"Could not resume the pending run: {exc}") from exc


@router.post("/retry")
@log_call
def retry(service: Runtime):
    try:
        return stream_response(service.retry_stream())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Agent runtime retry could not start")
        raise HTTPException(status_code=500, detail=f"Could not retry the unfinished run: {exc}") from exc


@router.post("/stop")
@log_call
async def stop(request: Request):
    # Stop must bypass the lock held by the active stream.
    service = require_runtime(request)
    try:
        return success({"stopped": service.stop()})
    except Exception as exc:
        LOGGER.exception("Agent runtime stop failed")
        raise HTTPException(status_code=500, detail=f"Could not stop the active run: {exc}") from exc


@router.post("/discard")
@log_call
def discard(service: Runtime):
    try:
        return success({"discarded": service.discard_pending_run()})
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Agent runtime discard failed")
        raise HTTPException(status_code=500, detail=f"Could not discard pending work: {exc}") from exc


@router.get("/sent-image/{filename}")
def get_sent_image(filename: str, service: Runtime):
    """Serve an image uploaded in chat."""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid image filename.")
    backend_root = service._orchestrator.agent_config.backend_root
    image_path = backend_root / "sent_images" / filename
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found.")
    ext = image_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = mime_map.get(ext, "application/octet-stream")
    return FileResponse(image_path, media_type=media_type)


@router.get("/sent-images")
def list_sent_images(service: Runtime):
    """List images uploaded in chat, newest first."""
    backend_root = service._orchestrator.agent_config.backend_root
    sent_dir = backend_root / "sent_images"
    if not sent_dir.is_dir():
        return success([])
    from datetime import datetime, timezone
    items = []
    for path in sorted(sent_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            stat = path.stat()
            items.append({
                "filename": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
    return success(items)


@router.delete("/sent-image/{filename}")
def delete_sent_image(filename: str, service: Runtime):
    """Delete an image uploaded in chat."""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid image filename.")
    backend_root = service._orchestrator.agent_config.backend_root
    image_path = backend_root / "sent_images" / filename
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found.")
    image_path.unlink()
    return success({"deleted": True, "filename": filename})
