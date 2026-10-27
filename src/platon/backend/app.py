"""FastAPI application with one AgentRuntimeService instance."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from threading import Lock

import uvicorn
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

from platon.app_logging import LOGGER
from platon.backend.routers.agent_runtime import router
from platon.backend.services.agent_runtime_service import AgentRuntimeService


def create_app(
    runtime_factory: Callable[..., AgentRuntimeService] = AgentRuntimeService,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.agent_runtime = None
        app.state.runtime_factory = runtime_factory
        app.state.runtime_lock = Lock()
        try:
            yield
        finally:
            # Stop can run while a stream holds the lock. Wait for the stream
            # before closing its resources, without blocking the event loop.
            service = app.state.agent_runtime
            if service is not None:
                try:
                    service.stop()
                except Exception:
                    LOGGER.exception("Agent runtime stop during shutdown failed")

            lock = app.state.runtime_lock
            await run_in_threadpool(lock.acquire)
            try:
                service = app.state.agent_runtime
                app.state.agent_runtime = None
                if service is not None:
                    await run_in_threadpool(service.close)
            finally:
                lock.release()

    app = FastAPI(title="Platon Backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app

if __name__ == "__main__":
    uvicorn.run(
        "platon.backend.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
