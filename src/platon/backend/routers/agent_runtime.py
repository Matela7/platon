"""HTTP endpoints calling AgentRuntimeService directly."""

from fastapi import APIRouter, Depends, HTTPException, Request

from platon.app_logging import LOGGER, log_call
from platon.backend.schemas.initialize_runtime import InitializeRuntime
from platon.backend.schemas.message_request import MessageRequest
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
def chat(body: MessageRequest, service: Runtime):
    try:
        return stream_response(service.stream(body.message))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Agent runtime chat could not start")
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
