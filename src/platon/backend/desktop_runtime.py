"""Small bootstrap helpers shared by the desktop launcher and frozen backend."""

import os
import sys
from pathlib import Path


def image_generation_available() -> bool:
    return sys.platform == "win32"


def prepare_data_directory() -> Path | None:
    """Make relative runtime paths writable, outside the extracted executable."""
    configured = os.environ.get("PLATON_DATA_DIR")
    if not configured:
        return None
    directory = Path(configured).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.chdir(directory)
    os.environ.setdefault("PLATON_DOCUMENT_DIR", str(directory / ".platon" / "agent" / "documents"))
    os.environ.setdefault("PLATON_CHROMA_DIR", str(directory / "chroma_data"))
    return directory


def main() -> None:
    # Must precede importing the application and its path-dependent dependencies.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    prepare_data_directory()
    if "--self-test" in sys.argv:
        self_test()
        return
    from dotenv import load_dotenv
    import uvicorn
    from platon.backend.app import create_app
    from platon.backend.utils.ollama_runtime_utils import ensure_local_ollama
    from platon.app_logging import LOGGER
    from threading import Thread

    load_dotenv(".env")

    def start_ollama():
        try:
            ensure_local_ollama()
        except Exception:
            LOGGER.warning("Ollama is unavailable; install/start Ollama before chatting", exc_info=True)

    Thread(target=start_ollama, name="ollama-startup", daemon=True).start()
    uvicorn.run(
        create_app(),
        host=os.getenv("PLATON_BACKEND_HOST", os.getenv("AGENT_API_HOST", "127.0.0.1")),
        port=int(os.getenv("PLATON_BACKEND_PORT", os.getenv("AGENT_API_PORT", "8000"))),
        log_level="info",
        loop="asyncio",
        http="h11",
        ws="none",
    )


def self_test() -> None:
    """Exercise frozen imports, bundled prompts and actual Python execution."""
    import json
    from tempfile import TemporaryDirectory
    from platon.backend.app import create_app
    from platon.agent.prompt_loader import load_prompt
    from platon.agent.tools.execution import create_execution_tools
    from sentence_transformers import SentenceTransformer
    # Import the real document embedding stack without downloading a model.
    assert callable(SentenceTransformer)
    app = create_app(document_factory=lambda: object())
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/health")
    assert endpoint()["status"] == "ok"
    assert load_prompt("react_prompt.md")
    with TemporaryDirectory(prefix="platon-self-test-") as directory:
        tools = {tool.name: tool for tool in create_execution_tools(Path(directory))}
        output = tools["run_python"].invoke({"code": "print('PLATON_PYTHON_OK')"})
        assert "PLATON_PYTHON_OK" in output, output
    print(json.dumps({"status": "ok", "checks": ["health", "prompts", "venv", "python", "document_embedding_imports"]}))


if __name__ == "__main__":
    main()
