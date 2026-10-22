"""Configuration model for one concrete agent's behavior."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Settings that describe agent behavior rather than infrastructure.

    Attributes:
        model_name: Primary Ollama model used by the agent.
        model_temperature: Sampling temperature used by the primary model.
        system_prompt: Prompt file loaded for the primary agent.
        max_history_messages: Number of recent message units kept in context.
        max_tool_output_chars: Maximum text returned by one tool invocation.
        keep_alive: How long Ollama keeps the model loaded after a request.
        num_ctx: Context window requested from Ollama for each model call.
        reasoning: Enable Ollama thinking for models that support it.
    """

    model_name: str = "gemma4:26b-a4b-it-qat"
    model_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    system_prompt: str = "react_prompt.md"
    max_history_messages: int = Field(default=24, ge=1)
    max_tool_output_chars: int = Field(default=20_000, ge=1_000)
    keep_alive: str | int = "30m"
    num_ctx: int = Field(default=16_384, ge=1)
    reasoning: bool = False
    debug: bool = True
    research_tool_limit: int = Field(default=6, ge=1)
    coding_tool_limit: int = Field(default=15, ge=1)
    database_tool_limit: int = Field(default=8, ge=1)
    execution_timeout_seconds: int = Field(default=120, ge=1)
    # DeepAgent paths are virtual paths relative to backend_root.
    backend_root: Path = Field(default_factory=lambda: Path.cwd() / ".platon" / "agent")
    skills: list[str] = Field(default_factory=lambda: ["/skills/"])
    memory: list[str] = Field(default_factory=lambda: ["/memory/AGENTS.md"])
