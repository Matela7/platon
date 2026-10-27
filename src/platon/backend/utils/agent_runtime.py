"""Runtime dependencies and HTTP response helpers."""

import json
from collections.abc import Iterator
from itertools import chain
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from platon.app_logging import LOGGER
from platon.backend.services.agent_runtime_service import AgentRuntimeService


def exclusive_access(request: Request):
    """Protect the single orchestrator, including the duration of a stream."""
    lock = request.app.state.runtime_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Agent runtime is busy.")
    try:
        yield
    finally:
        lock.release()


def require_runtime(request: Request) -> AgentRuntimeService:
    service = request.app.state.agent_runtime
    if service is None:
        raise HTTPException(409, "Initialize the agent runtime first.")
    return service


def get_runtime(request: Request, access=Depends(exclusive_access)) -> AgentRuntimeService:
    return require_runtime(request)


Runtime = Annotated[AgentRuntimeService, Depends(get_runtime)]


def success(data):
    return JSONResponse(content=jsonable_encoder({"status": "success", "data": data}))


def stream_response(events: Iterator[dict]) -> StreamingResponse:
    # Start before sending headers, so validation can still return an HTTP error.
    first = next(events)

    def encode():
        try:
            for event in chain((first,), events):
                if event["type"] == "result":
                    payload = dict(event["data"])
                    payload.pop("result", None)
                    event = {**event, "data": payload}
                yield json.dumps(jsonable_encoder(event), ensure_ascii=False) + "\n"
        except Exception as exc:
            LOGGER.exception("Agent response stream failed")
            yield json.dumps({"type": "error", "data": {"message": f"Execution failed: {exc}"}}, ensure_ascii=False) + "\n"
        finally:
            events.close()

    return StreamingResponse(
        encode(), media_type="application/x-ndjson",
        background=BackgroundTask(events.close),
    )
