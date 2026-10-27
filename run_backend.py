#!/usr/bin/env python3
"""Start the FastAPI backend after ensuring local Ollama is available."""

from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv

from platon.ollama_runtime import ensure_local_ollama


def main() -> int:
    load_dotenv(dotenv_path=".env")
    ensure_local_ollama()
    uvicorn.run(
        "platon.backend.app:create_app",
        factory=True,
        host=os.getenv("AGENT_API_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENT_API_PORT", "8000")),
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
