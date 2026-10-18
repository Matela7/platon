"""Platon multi-agent package with lazy public imports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "AgentOrchestrator",
    "BaseAgent",
    "DeepAgent",
    "CodingAgent",
    "DatabaseAgent",
    "ResearchAgent",
    "SupervisorAgent",
]

_PUBLIC_IMPORTS = {
    "AgentOrchestrator": ("platon.agent.agent_orchestrator", "AgentOrchestrator"),
    "BaseAgent": ("platon.agent.base_agent", "BaseAgent"),
    "DeepAgent": ("platon.agent.deep_agent", "DeepAgent"),
    "CodingAgent": ("platon.agent.agents", "CodingAgent"),
    "DatabaseAgent": ("platon.agent.agents", "DatabaseAgent"),
    "ResearchAgent": ("platon.agent.agents", "ResearchAgent"),
    "SupervisorAgent": ("platon.agent.agents", "SupervisorAgent"),
}


def __getattr__(name: str) -> Any:
    """Load public classes only when callers request them."""
    try:
        module_name, attribute = _PUBLIC_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module 'agent' has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
