from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class AgentConfig(BaseModel):
    """Runtime configuration for the base research agent.

    Attributes:
        model_name: Primary Ollama model used by the agent.
        base_url: Ollama server base URL.
        persist_dir: Directory used by vector store persistence.
        working_dir: Agent working directory for local files.
        system_prompt: Prompt file name loaded from prompts directory.
        sqlite_path: Optional explicit path to conversation SQLite database.
        max_history_messages: Number of recent message units kept in context.
        keep_alive: How long Ollama keeps the model loaded after a request.
        max_tool_output_chars: Maximum text returned by one tool invocation.
        research_prompt: Prompt file for the research subagent.
        workspace_prompt: Prompt file for the workspace subagent.
        execution_prompt: Prompt file for the execution subagent.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str = "ornith:9b-q4_K_M"
    base_url: str = "http://localhost:11434"
    persist_dir: str = "./chroma_data"
    working_dir: Path = Path("./")
    system_prompt: str = "react_prompt.md"
    sqlite_path: str | Path | None = None
    max_history_messages: int = Field(default=24, ge=1)
    keep_alive: str | int = "30m"
    max_tool_output_chars: int = Field(default=20_000, ge=1_000)
    research_prompt: str = "subagents/research.md"
    workspace_prompt: str = "subagents/workspace.md"
    execution_prompt: str = "subagents/execution.md"
