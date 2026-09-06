"""Minimal technical base shared by every concrete agent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent.models.agent_config import AgentConfig
from agent.prompt_loader import load_prompt


class BaseAgent:
    """Hold a model, a prompt and tools, and compile a LangChain agent.

    Role-specific dependencies belong to subclasses. In particular this class
    knows nothing about Chroma, RAG, workspaces, or delegation.
    """

    agent_name = "base_agent"
    prompt_path: str | None = None

    def __init__(
        self,
        model: BaseChatModel,
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.model = model
        self.tools_list = list(tools_list or [])
        self.prompt = prompt
        self.checkpointer = checkpointer

    @property
    def model_name(self) -> str:
        """Return a stable model label for tracing metadata."""
        for attribute in ("model", "model_name"):
            value = getattr(self.model, attribute, None)
            if isinstance(value, str) and value:
                return value
        return type(self.model).__name__

    def _default_prompt(self) -> str:
        """Load the prompt declared by the concrete agent class."""
        if self.prompt_path is None:
            raise NotImplementedError(
                f"{type(self).__name__} must define prompt_path or receive prompt"
            )
        return load_prompt(self.prompt_path)

    def _middleware(self) -> list[Any]:
        """Return role-specific execution guards for a freshly compiled graph."""
        return []
    # tu warto abstrakcjyna funkcje pierdolnac
    def create_agent(self, prompt: str | None = None) -> Any:
        """Compile this role into an invokable LangChain graph."""
        system_prompt = prompt or self.prompt or self._default_prompt()
        return create_agent(
            model=self.model,
            tools=self.tools_list,
            system_prompt=system_prompt,
            middleware=self._middleware(),
            checkpointer=self.checkpointer,
            name=self.agent_name,
            debug=False,
        )

    def invoke(
        self,
        task: str,
        *,
        context_messages: Sequence[BaseMessage] | None = None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        """Run a task with optional prior conversation supplied by an adapter."""
        if not task.strip():
            raise ValueError("task must not be empty")
        messages = [
            message
            for message in context_messages or []
            if not isinstance(message, SystemMessage)
        ]
        messages.append(HumanMessage(content=task))
        return self.create_agent().invoke(
            {"messages": messages},
            config=config,
        )
