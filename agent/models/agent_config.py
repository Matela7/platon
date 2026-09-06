"""Configuration model for one concrete agent's behavior."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Settings that describe agent behavior rather than infrastructure.

    Attributes:
        model_name: Primary Ollama model used by the agent.
        system_prompt: Prompt file loaded for the primary agent.
        max_history_messages: Number of recent message units kept in context.
        max_tool_output_chars: Maximum text returned by one tool invocation.
        keep_alive: How long Ollama keeps the model loaded after a request.
    """

    model_name: str = "aratan/Ornith-1.5-35B-A3B-Uncensored-GGUF:Q4_K_M"
    system_prompt: str = "react_prompt.md"
    max_history_messages: int = Field(default=24, ge=1)
    max_tool_output_chars: int = Field(default=20_000, ge=1_000)
    keep_alive: str | int = "30m"
