"""FastAPI application with one AgentRuntimeService instance."""

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from threading import Lock

import uvicorn
from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

from platon.app_logging import LOGGER
from platon.backend.routers.agent_runtime import router
from platon.backend.routers.documents import router as documents_router
from platon.backend.routers.images import router as images_router
from platon.backend.schemas.initialize_runtime import INITIALIZE_OPENAPI_EXAMPLE
from platon.backend.services.document_service import DocumentService
from platon.backend.services.agent_runtime_service import AgentRuntimeService
from platon.backend.utils.ollama_runtime_utils import ensure_local_ollama


def create_app(
    runtime_factory: Callable[..., AgentRuntimeService] = AgentRuntimeService,
    document_factory: Callable[..., DocumentService] = DocumentService,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.agent_runtime = None
        app.state.document_service = document_factory()
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
    app.include_router(documents_router)
    app.include_router(images_router)

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        schema["paths"]["/api/v1/agent-runtime/initialize"]["post"]["requestBody"]["content"][
            "application/json"
        ]["example"] = INITIALIZE_OPENAPI_EXAMPLE
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


if __name__ == "__main__":
    load_dotenv(dotenv_path=".env")
    ensure_local_ollama()
    uvicorn.run(
        "platon.backend.app:create_app",
        factory=True,
        host=os.getenv("AGENT_API_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENT_API_PORT", "8000")),
        log_level="info",
    )
