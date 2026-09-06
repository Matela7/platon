"""Runtime configuration owned by the agent orchestrator."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class AgentOrchestratorConfig(BaseModel):
    """Settings passed by the orchestrator to each concrete agent.

    Attributes:
        base_url: Ollama server base URL.
        persist_dir: Directory used by Chroma persistence.
        working_dir: Root workspace available to the agent and its tools.
        sqlite_path: Optional explicit path to the thread SQLite database.
    """

    base_url: str = "http://localhost:11434"
    persist_dir: str = "./chroma_data"
    working_dir: Path = Path("./")
    sqlite_path: str | Path | None = None
